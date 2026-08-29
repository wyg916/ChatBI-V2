from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.config import get_settings
from app.models import DataSource
from app.query.contracts import ExecutionResult
from app.services.datasources import build_connector, runtime_dialect


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def result_signature(columns: list[str], rows: list[dict[str, Any]], *, order_independent: bool = True) -> str:
    normalized_rows = [
        {column: json_value(row.get(column)) for column in columns}
        for row in rows
    ]
    if order_independent:
        normalized_rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload = json.dumps(
        {"columns": columns, "rows": normalized_rows},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _FairBoundedSemaphore:
    """A bounded FIFO semaphore that supports cancellation while queued."""

    def __init__(self, value: int) -> None:
        if value < 1:
            raise ValueError("semaphore initial value must be at least one")
        self._capacity = value
        self._available = value
        self._condition = threading.Condition()
        self._waiters: deque[object] = deque()

    def acquire_until(
        self,
        *,
        timeout_seconds: float,
        cancellation_event: threading.Event | None = None,
    ) -> tuple[bool, bool]:
        ticket = object()
        deadline = time.perf_counter() + max(0.0, timeout_seconds)
        with self._condition:
            self._waiters.append(ticket)
            while True:
                if cancellation_event is not None and cancellation_event.is_set():
                    self._waiters.remove(ticket)
                    self._condition.notify_all()
                    return False, True
                if self._waiters[0] is ticket and self._available > 0:
                    self._waiters.popleft()
                    self._available -= 1
                    self._condition.notify_all()
                    return True, False
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    self._waiters.remove(ticket)
                    self._condition.notify_all()
                    return False, False
                self._condition.wait(
                    timeout=min(0.05, remaining) if cancellation_event is not None else remaining
                )

    def release(self) -> None:
        with self._condition:
            if self._available >= self._capacity:
                raise ValueError("Semaphore released too many times")
            self._available += 1
            self._condition.notify_all()


class QueryExecutor:
    _semaphore: _FairBoundedSemaphore | None = None
    _semaphore_size: int | None = None
    _semaphore_lock = threading.Lock()

    @classmethod
    def _limit_semaphore(cls) -> _FairBoundedSemaphore:
        size = max(1, get_settings().query_concurrency)
        with cls._semaphore_lock:
            if cls._semaphore is None or cls._semaphore_size != size:
                cls._semaphore = _FairBoundedSemaphore(size)
                cls._semaphore_size = size
            return cls._semaphore

    @staticmethod
    def _acquire_slot(
        semaphore: threading.BoundedSemaphore | _FairBoundedSemaphore,
        *,
        timeout_ms: int,
        cancellation_event: threading.Event | None = None,
    ) -> tuple[bool, bool]:
        """Wait for bounded query capacity without ignoring cancellation.

        A transiently full execution pool is backpressure, not an immediate
        query failure.  Keep the wait bounded by the same request-level timeout
        and poll cancellation so disconnected streaming clients do not remain
        queued until the full deadline.
        """

        timeout_seconds = max(0, timeout_ms) / 1000
        if isinstance(semaphore, _FairBoundedSemaphore):
            return semaphore.acquire_until(
                timeout_seconds=timeout_seconds,
                cancellation_event=cancellation_event,
            )

        deadline = time.perf_counter() + timeout_seconds
        while True:
            if cancellation_event is not None and cancellation_event.is_set():
                return False, True
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return False, False
            if semaphore.acquire(timeout=min(0.05, remaining)):
                return True, False

    @staticmethod
    def _prepare_postgres_transaction(connection: Any, datasource: DataSource, timeout_ms: int) -> None:
        """Apply the read-only boundary and the datasource's approved schema.

        NL2SQL plans may legally use an unqualified table name after SqlGuard has
        checked it against ``allowed_tables``.  PostgreSQL connections do not
        otherwise inherit the datasource metadata schema, so EXPLAIN and the
        real query could disagree depending on whether the model happened to
        qualify the table.  Keep both operations in the same, quoted search path.
        """

        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        if datasource.schema:
            quoted_schema = connection.dialect.identifier_preparer.quote(datasource.schema)
            connection.exec_driver_sql(f"SET LOCAL search_path TO {quoted_schema}")

    def execute(
        self,
        *,
        datasource: DataSource,
        normalized_sql: str,
        row_limit: int,
        timeout_ms: int,
        cancellation_event: threading.Event | None = None,
    ) -> ExecutionResult:
        dialect = runtime_dialect(datasource)
        if cancellation_event is not None and cancellation_event.is_set():
            return ExecutionResult(
                status="FAILED", datasource_id=datasource.id, dialect=dialect,
                normalized_sql=normalized_sql, error_code="QUERY_CANCELLED",
                error_message="Query was cancelled before execution",
            )
        semaphore = self._limit_semaphore()
        acquired, cancelled = self._acquire_slot(
            semaphore,
            timeout_ms=timeout_ms,
            cancellation_event=cancellation_event,
        )
        if not acquired:
            if cancelled:
                return ExecutionResult(
                    status="FAILED", datasource_id=datasource.id, dialect=dialect,
                    normalized_sql=normalized_sql, error_code="QUERY_CANCELLED",
                    error_message="Query was cancelled while waiting for execution capacity",
                )
            return ExecutionResult(
                status="CONCURRENCY_LIMIT", datasource_id=datasource.id, dialect=dialect,
                normalized_sql=normalized_sql, error_code="QUERY_CONCURRENCY_LIMIT",
                error_message="Timed out while waiting for query execution capacity",
            )
        started = time.perf_counter()
        engine = None
        try:
            connector = build_connector(datasource)
            engine = connector._engine()  # Connector owns URL construction and credentials.
            with engine.connect() as connection:
                monitor_stop = threading.Event()
                monitor = None
                if cancellation_event is not None and dialect == "postgresql":
                    def cancel_on_disconnect() -> None:
                        while not monitor_stop.wait(0.02):
                            if cancellation_event.is_set():
                                try:
                                    connection.connection.driver_connection.cancel()
                                except Exception:
                                    pass
                                return

                    monitor = threading.Thread(
                        target=cancel_on_disconnect, name="chatbi-query-cancel", daemon=True,
                    )
                    monitor.start()
                try:
                    if dialect == "postgresql":
                        with connection.begin():
                            self._prepare_postgres_transaction(connection, datasource, timeout_ms)
                            result = connection.execute(text(normalized_sql))
                            keys = list(result.keys())
                            raw_rows = result.mappings().fetchmany(row_limit)
                            types = [str(item.type) for item in result.cursor.description] if False else []
                    else:
                        connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_ms)}")
                        connection.commit()
                        with connection.begin():
                            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                            result = connection.execute(text(normalized_sql))
                            keys = list(result.keys())
                            raw_rows = result.mappings().fetchmany(row_limit)
                            types = []
                finally:
                    monitor_stop.set()
                    if monitor is not None:
                        monitor.join(timeout=0.1)
            rows = [{key: json_value(row[key]) for key in keys} for row in raw_rows]
            duration_ms = round((time.perf_counter() - started) * 1000)
            signature = result_signature(keys, rows)
            return ExecutionResult(
                status="SUCCEEDED", columns=keys, column_types=types or ["unknown"] * len(keys), rows=rows,
                row_count=len(rows), truncated=len(rows) >= row_limit, duration_ms=duration_ms,
                datasource_id=datasource.id, dialect=dialect, normalized_sql=normalized_sql,
                result_signature=signature,
            )
        except (OperationalError, DBAPIError) as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            message = str(getattr(exc, "orig", exc))
            lowered = message.lower()
            if "timeout" in lowered or "statement timeout" in lowered or "max_execution_time" in lowered:
                status, code = "TIMEOUT", "QUERY_TIMEOUT"
            elif "permission" in lowered or "denied" in lowered or "read-only" in lowered:
                status, code = "FAILED", "QUERY_PERMISSION_DENIED"
            else:
                status, code = "FAILED", "QUERY_EXECUTION_ERROR"
            return ExecutionResult(
                status=status, duration_ms=duration_ms, datasource_id=datasource.id, dialect=dialect,
                normalized_sql=normalized_sql, error_code=code, error_message=message[:1000],
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            return ExecutionResult(
                status="FAILED", duration_ms=duration_ms, datasource_id=datasource.id, dialect=dialect,
                normalized_sql=normalized_sql, error_code="QUERY_EXECUTION_ERROR", error_message=str(exc)[:1000],
            )
        finally:
            if engine is not None:
                engine.dispose()
            semaphore.release()

    def explain(
        self,
        *,
        datasource: DataSource,
        normalized_sql: str,
        timeout_ms: int,
    ) -> ExecutionResult:
        """Explain a statement only after the caller has passed it through SqlGuard."""
        dialect = runtime_dialect(datasource)
        semaphore = self._limit_semaphore()
        acquired, _ = self._acquire_slot(semaphore, timeout_ms=timeout_ms)
        if not acquired:
            return ExecutionResult(
                status="CONCURRENCY_LIMIT", datasource_id=datasource.id, dialect=dialect,
                normalized_sql=normalized_sql, error_code="QUERY_CONCURRENCY_LIMIT",
                error_message="Timed out while waiting for query execution capacity",
            )
        started = time.perf_counter()
        engine = None
        try:
            connector = build_connector(datasource)
            engine = connector._engine()
            prefix = "EXPLAIN (FORMAT JSON) " if dialect == "postgresql" else "EXPLAIN FORMAT=JSON "
            with engine.connect() as connection:
                if dialect == "postgresql":
                    with connection.begin():
                        self._prepare_postgres_transaction(connection, datasource, timeout_ms)
                        value = connection.execute(text(prefix + normalized_sql)).scalar_one()
                else:
                    connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_ms)}")
                    connection.commit()
                    with connection.begin():
                        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                        value = connection.execute(text(prefix + normalized_sql)).scalar_one()
            rows = [{"plan": json_value(value)}]
            duration_ms = round((time.perf_counter() - started) * 1000)
            return ExecutionResult(
                status="SUCCEEDED", columns=["plan"], column_types=["json"], rows=rows,
                row_count=1, duration_ms=duration_ms, datasource_id=datasource.id,
                dialect=dialect, normalized_sql=normalized_sql,
                result_signature=result_signature(["plan"], rows),
            )
        except (OperationalError, DBAPIError) as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            message = str(getattr(exc, "orig", exc))
            code = "QUERY_TIMEOUT" if "timeout" in message.lower() else "QUERY_EXPLAIN_ERROR"
            return ExecutionResult(
                status="TIMEOUT" if code == "QUERY_TIMEOUT" else "FAILED",
                duration_ms=duration_ms, datasource_id=datasource.id, dialect=dialect,
                normalized_sql=normalized_sql, error_code=code, error_message=message[:1000],
            )
        except Exception as exc:
            return ExecutionResult(
                status="FAILED", duration_ms=round((time.perf_counter() - started) * 1000),
                datasource_id=datasource.id, dialect=dialect, normalized_sql=normalized_sql,
                error_code="QUERY_EXPLAIN_ERROR", error_message=str(exc)[:1000],
            )
        finally:
            if engine is not None:
                engine.dispose()
            semaphore.release()
