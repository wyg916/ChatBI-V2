from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.config import get_settings
from app.models import DataSource
from app.query.contracts import ExecutionResult
from app.services.datasources import build_connector


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


class QueryExecutor:
    _semaphore: threading.BoundedSemaphore | None = None
    _semaphore_size: int | None = None

    @classmethod
    def _limit_semaphore(cls) -> threading.BoundedSemaphore:
        size = max(1, get_settings().query_concurrency)
        if cls._semaphore is None or cls._semaphore_size != size:
            cls._semaphore = threading.BoundedSemaphore(size)
            cls._semaphore_size = size
        return cls._semaphore

    def execute(
        self,
        *,
        datasource: DataSource,
        normalized_sql: str,
        row_limit: int,
        timeout_ms: int,
        cancellation_event: threading.Event | None = None,
    ) -> ExecutionResult:
        if cancellation_event is not None and cancellation_event.is_set():
            return ExecutionResult(
                status="FAILED", datasource_id=datasource.id, dialect=datasource.type,
                normalized_sql=normalized_sql, error_code="QUERY_CANCELLED",
                error_message="Query was cancelled before execution",
            )
        semaphore = self._limit_semaphore()
        if not semaphore.acquire(blocking=False):
            return ExecutionResult(
                status="CONCURRENCY_LIMIT", datasource_id=datasource.id, dialect=datasource.type,
                normalized_sql=normalized_sql, error_code="QUERY_CONCURRENCY_LIMIT",
                error_message="The query concurrency limit has been reached",
            )
        started = time.perf_counter()
        engine = None
        try:
            connector = build_connector(datasource)
            engine = connector._engine()  # Connector owns URL construction and credentials.
            with engine.connect() as connection:
                monitor_stop = threading.Event()
                monitor = None
                if cancellation_event is not None and datasource.type == "postgresql":
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
                    if datasource.type == "postgresql":
                        with connection.begin():
                            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                            connection.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
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
                datasource_id=datasource.id, dialect=datasource.type, normalized_sql=normalized_sql,
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
                status=status, duration_ms=duration_ms, datasource_id=datasource.id, dialect=datasource.type,
                normalized_sql=normalized_sql, error_code=code, error_message=message[:1000],
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            return ExecutionResult(
                status="FAILED", duration_ms=duration_ms, datasource_id=datasource.id, dialect=datasource.type,
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
        semaphore = self._limit_semaphore()
        if not semaphore.acquire(blocking=False):
            return ExecutionResult(
                status="CONCURRENCY_LIMIT", datasource_id=datasource.id, dialect=datasource.type,
                normalized_sql=normalized_sql, error_code="QUERY_CONCURRENCY_LIMIT",
                error_message="The query concurrency limit has been reached",
            )
        started = time.perf_counter()
        engine = None
        try:
            connector = build_connector(datasource)
            engine = connector._engine()
            prefix = "EXPLAIN (FORMAT JSON) " if datasource.type == "postgresql" else "EXPLAIN FORMAT=JSON "
            with engine.connect() as connection:
                if datasource.type == "postgresql":
                    with connection.begin():
                        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                        connection.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
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
                dialect=datasource.type, normalized_sql=normalized_sql,
                result_signature=result_signature(["plan"], rows),
            )
        except (OperationalError, DBAPIError) as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            message = str(getattr(exc, "orig", exc))
            code = "QUERY_TIMEOUT" if "timeout" in message.lower() else "QUERY_EXPLAIN_ERROR"
            return ExecutionResult(
                status="TIMEOUT" if code == "QUERY_TIMEOUT" else "FAILED",
                duration_ms=duration_ms, datasource_id=datasource.id, dialect=datasource.type,
                normalized_sql=normalized_sql, error_code=code, error_message=message[:1000],
            )
        except Exception as exc:
            return ExecutionResult(
                status="FAILED", duration_ms=round((time.perf_counter() - started) * 1000),
                datasource_id=datasource.id, dialect=datasource.type, normalized_sql=normalized_sql,
                error_code="QUERY_EXPLAIN_ERROR", error_message=str(exc)[:1000],
            )
        finally:
            if engine is not None:
                engine.dispose()
            semaphore.release()
