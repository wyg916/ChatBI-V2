import threading
import time
from types import SimpleNamespace

from app.query.executor import QueryExecutor, _FairBoundedSemaphore


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


def test_fair_query_slots_preserve_fifo_order_under_contention() -> None:
    semaphore = _FairBoundedSemaphore(1)
    acquired, cancelled = semaphore.acquire_until(timeout_seconds=0.1)
    assert acquired is True
    assert cancelled is False

    order: list[str] = []
    first_started = threading.Event()
    second_started = threading.Event()

    def waiter(name: str, started: threading.Event) -> None:
        started.set()
        acquired_slot, was_cancelled = semaphore.acquire_until(timeout_seconds=1)
        assert acquired_slot is True
        assert was_cancelled is False
        order.append(name)
        time.sleep(0.01)
        semaphore.release()

    first = threading.Thread(target=waiter, args=("first", first_started))
    second = threading.Thread(target=waiter, args=("second", second_started))
    first.start()
    assert first_started.wait(timeout=0.2)
    time.sleep(0.01)
    second.start()
    assert second_started.wait(timeout=0.2)
    time.sleep(0.01)

    semaphore.release()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert order == ["first", "second"]


def test_fair_query_slots_remove_cancelled_waiter_without_leaking_capacity() -> None:
    semaphore = _FairBoundedSemaphore(1)
    acquired, _ = semaphore.acquire_until(timeout_seconds=0.1)
    assert acquired is True

    cancellation = threading.Event()
    outcome: list[tuple[bool, bool]] = []
    waiter = threading.Thread(
        target=lambda: outcome.append(
            semaphore.acquire_until(timeout_seconds=1, cancellation_event=cancellation)
        )
    )
    waiter.start()
    time.sleep(0.02)
    cancellation.set()
    waiter.join(timeout=1)

    assert outcome == [(False, True)]
    semaphore.release()
    acquired_again, cancelled_again = semaphore.acquire_until(timeout_seconds=0.1)
    assert acquired_again is True
    assert cancelled_again is False
    semaphore.release()


def test_query_executor_creates_one_fair_capacity_gate_under_concurrent_startup(monkeypatch) -> None:
    monkeypatch.setattr(QueryExecutor, "_semaphore", None)
    monkeypatch.setattr(QueryExecutor, "_semaphore_size", None)
    gates: list[_FairBoundedSemaphore] = []
    start = threading.Barrier(21)

    def resolve_gate() -> None:
        start.wait()
        gates.append(QueryExecutor._limit_semaphore())

    workers = [threading.Thread(target=resolve_gate) for _ in range(20)]
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join(timeout=1)

    assert all(not worker.is_alive() for worker in workers)
    assert len({id(gate) for gate in gates}) == 1
