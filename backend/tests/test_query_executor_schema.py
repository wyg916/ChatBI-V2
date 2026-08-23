import threading
import time
from types import SimpleNamespace

from app.query.executor import QueryExecutor


class _Preparer:
    @staticmethod
    def quote(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'


class _Connection:
    dialect = SimpleNamespace(identifier_preparer=_Preparer())

    def __init__(self) -> None:
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)


def test_postgres_transaction_uses_quoted_datasource_schema() -> None:
    connection = _Connection()

    QueryExecutor._prepare_postgres_transaction(
        connection,
        SimpleNamespace(schema='tenant"analytics'),
        12_345,
    )

    assert connection.statements == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = 12345",
        'SET LOCAL search_path TO "tenant""analytics"',
    ]


def test_postgres_transaction_omits_search_path_without_schema() -> None:
    connection = _Connection()

    QueryExecutor._prepare_postgres_transaction(
        connection,
        SimpleNamespace(schema=None),
        30_000,
    )

    assert connection.statements == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = 30000",
    ]


def test_query_capacity_waits_for_a_bounded_slot() -> None:
    semaphore = threading.BoundedSemaphore(1)
    assert semaphore.acquire(blocking=False)
    releaser = threading.Timer(0.02, semaphore.release)
    releaser.start()
    try:
        acquired, cancelled = QueryExecutor._acquire_slot(semaphore, timeout_ms=500)
        assert acquired is True
        assert cancelled is False
        semaphore.release()
    finally:
        releaser.join(timeout=1)


def test_query_capacity_wait_honors_cancellation() -> None:
    semaphore = threading.BoundedSemaphore(1)
    cancellation_event = threading.Event()
    cancellation_event.set()

    started = time.perf_counter()
    acquired, cancelled = QueryExecutor._acquire_slot(
        semaphore,
        timeout_ms=5_000,
        cancellation_event=cancellation_event,
    )

    assert acquired is False
    assert cancelled is True
    assert time.perf_counter() - started < 0.1
