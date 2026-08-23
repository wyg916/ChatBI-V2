from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from app.model_gateway.configuration import load_control_config
from app.model_gateway.contracts import ModelRequest, ModelResponse, RequestContext


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_YES = {"1", "true", "yes", "on"}


class TestCostControlError(RuntimeError):
    """Fail-closed error raised before an unauthorized paid test call."""


class TestExecutionLevel(StrEnum):
    LEVEL0 = "LEVEL0"
    LEVEL1 = "LEVEL1"
    LEVEL2 = "LEVEL2"


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in _YES


def _level(value: str | None) -> TestExecutionLevel:
    normalized = str(value or "LEVEL0").strip().upper().replace("_", "")
    aliases = {"0": TestExecutionLevel.LEVEL0, "L0": TestExecutionLevel.LEVEL0,
               "LEVEL0": TestExecutionLevel.LEVEL0,
               "1": TestExecutionLevel.LEVEL1, "L1": TestExecutionLevel.LEVEL1,
               "LEVEL1": TestExecutionLevel.LEVEL1,
               "2": TestExecutionLevel.LEVEL2, "L2": TestExecutionLevel.LEVEL2,
               "LEVEL2": TestExecutionLevel.LEVEL2}
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise TestCostControlError(f"UNKNOWN_TEST_EXECUTION_LEVEL:{value}") from exc


@dataclass(frozen=True)
class PaidTestAttempt:
    call_id: str
    provider: str
    model: str
    retry_count: int


class TestCostController:
    """Opt-in paid-test guard at the sole external Model Gateway boundary.

    Production is unchanged when CHATBI_TEST_COST_CONTROL is unset. An explicit
    MockTransport/recorded transport is free and therefore bypasses reservations.
    Real Level 0 transport is always blocked. Level 1 and Level 2 require explicit
    authorization, bounded scope, an external SQLite ledger and a hard budget.
    """

    def __init__(self, *, environ: Mapping[str, str] | None = None) -> None:
        self.environ = dict(os.environ if environ is None else environ)
        self.policy = load_control_config("test_cost_control.yaml")
        self.enabled = _enabled(self.environ.get("CHATBI_TEST_COST_CONTROL"))
        self.level = _level(self.environ.get("CHATBI_TEST_EXECUTION_LEVEL"))

    @property
    def paid_providers(self) -> set[str]:
        return {str(value) for value in self.policy["paid_providers"]}

    @property
    def gate(self) -> str:
        return self.environ.get("CHATBI_TEST_GATE", "unspecified").strip().lower()

    def output_token_limit(self) -> int:
        key = "complex_max_output_tokens" if any(
            marker in self.gate for marker in ("complex", "agent")
        ) else "default_max_output_tokens"
        return int(self.policy["limits"][key])

    def limit_output_tokens(self, configured: int) -> int:
        if not self.enabled:
            return configured
        return min(configured, self.output_token_limit())

    def limit_attempts(self, configured_attempts: int) -> int:
        if not self.enabled:
            return configured_attempts
        max_attempts = int(self.policy["limits"]["provider_max_retry"]) + 1
        return max(1, min(configured_attempts, max_attempts))

    def validate_configuration(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "level": self.level.value, "paid_calls_allowed": False}
        if self.level == TestExecutionLevel.LEVEL0:
            return {
                "enabled": True,
                "level": self.level.value,
                "paid_calls_allowed": False,
                "provider_mode": "DETERMINISTIC_CONTROLLED_OR_RECORDED",
                "max_output_tokens": self.output_token_limit(),
            }

        if not _enabled(self.environ.get("CHATBI_PAID_GATE_AUTHORIZED")):
            raise TestCostControlError("PAID_GATE_AUTHORIZED_REQUIRED")
        tested_sha = self.environ.get("CHATBI_TEST_SHA", "").strip().lower()
        if not _SHA_RE.fullmatch(tested_sha):
            raise TestCostControlError("CHATBI_TEST_SHA_MUST_BE_FULL_SHA")
        required = (
            "CHATBI_TEST_RUN_ID",
            "CHATBI_TEST_CASE_ID",
            "CHATBI_TEST_GATE",
            "CHATBI_TEST_ALLOWED_PROVIDERS",
            "CHATBI_TEST_COST_LEDGER_PATH",
        )
        missing = [name for name in required if not self.environ.get(name, "").strip()]
        if missing:
            raise TestCostControlError("MISSING_PAID_TEST_METADATA:" + ",".join(missing))

        affected_path = self.environ.get("CHATBI_TEST_AFFECTED_PATH", "").strip().lower()
        if self.level == TestExecutionLevel.LEVEL1:
            if affected_path not in set(self.policy["level1_affected_paths"]):
                raise TestCostControlError("LEVEL1_AFFECTED_PATH_NOT_ALLOWED")
        else:
            if not _enabled(self.environ.get("CHATBI_FINAL_CERTIFICATION")):
                raise TestCostControlError("FINAL_CERTIFICATION_FLAG_REQUIRED")
            if not _enabled(self.environ.get("CHATBI_PAID_TEST_CACHE_BYPASS")):
                raise TestCostControlError("PAID_TEST_CACHE_BYPASS_REQUIRED")
            final_sha = self.environ.get("CHATBI_TEST_FINAL_SHA", "").strip().lower()
            if final_sha != tested_sha:
                raise TestCostControlError("FINAL_CERTIFICATION_SHA_MISMATCH")
            self._validate_level0_receipt(tested_sha)

        budget_class = self.environ.get(
            "CHATBI_TEST_BUDGET_CLASS",
            "final_certification" if self.level == TestExecutionLevel.LEVEL2 else "targeted_live_regression",
        ).strip().lower()
        budgets = self.policy["budgets_cny"]
        if budget_class not in budgets or budget_class == "daily_hard_cap":
            raise TestCostControlError("UNKNOWN_TEST_BUDGET_CLASS")
        hard_limit = float(budgets[budget_class])
        requested_budget = float(self.environ.get("CHATBI_TEST_BUDGET_CNY", hard_limit))
        if requested_budget <= 0 or requested_budget > hard_limit:
            raise TestCostControlError(
                f"TEST_BUDGET_EXCEEDED REQUIRED_ESTIMATED_COST={requested_budget:.8f} "
                f"REASON={budget_class}_hard_cap_{hard_limit:.2f}"
            )
        return {
            "enabled": True,
            "level": self.level.value,
            "paid_calls_allowed": True,
            "tested_sha": tested_sha,
            "budget_class": budget_class,
            "run_budget_cny": requested_budget,
            "daily_hard_cap_cny": float(budgets["daily_hard_cap"]),
            "max_output_tokens": self.output_token_limit(),
            "provider_max_retry": int(self.policy["limits"]["provider_max_retry"]),
            "affected_path": affected_path or "final_certification",
        }

    def _validate_level0_receipt(self, tested_sha: str) -> None:
        raw_path = self.environ.get("CHATBI_LEVEL0_RECEIPT", "").strip()
        if not raw_path:
            raise TestCostControlError("LEVEL0_RECEIPT_REQUIRED")
        path = Path(raw_path)
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TestCostControlError("LEVEL0_RECEIPT_UNREADABLE") from exc
        if receipt.get("tested_sha") != tested_sha or receipt.get("level0_all_pass") is not True:
            raise TestCostControlError("LEVEL0_RECEIPT_SHA_OR_STATUS_MISMATCH")
        gates = receipt.get("gates") or {}
        missing = [name for name in self.policy["required_level0_gates"] if gates.get(name) != "PASS"]
        if missing:
            raise TestCostControlError("LEVEL0_REQUIRED_GATES_NOT_PASS:" + ",".join(missing))

    def _allowed_providers(self) -> set[str]:
        raw = self.environ.get("CHATBI_TEST_ALLOWED_PROVIDERS", "").strip()
        return {part.strip().lower() for part in raw.split(",") if part.strip()} or self.paid_providers

    def _ledger_path(self) -> Path:
        return Path(self.environ["CHATBI_TEST_COST_LEDGER_PATH"]).expanduser().resolve()

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paid_test_calls (
              call_id TEXT PRIMARY KEY,
              test_date TEXT NOT NULL,
              test_run_id TEXT NOT NULL,
              tested_sha TEXT NOT NULL,
              case_id TEXT NOT NULL,
              gate_name TEXT NOT NULL,
              provider TEXT NOT NULL,
              model TEXT NOT NULL,
              status TEXT NOT NULL,
              input_tokens INTEGER NOT NULL DEFAULT 0,
              cached_input_tokens INTEGER NOT NULL DEFAULT 0,
              output_tokens INTEGER NOT NULL DEFAULT 0,
              reserved_cost_cny REAL NOT NULL,
              actual_cost_cny REAL NOT NULL DEFAULT 0,
              retry_count INTEGER NOT NULL DEFAULT 0,
              error_code TEXT,
              created_at TEXT NOT NULL,
              completed_at TEXT
            )
            """
        )
        return connection

    def reserve_attempt(
        self,
        *,
        provider: str,
        model: str,
        request: ModelRequest,
        context: RequestContext,
        estimated_cost_cny: float,
        retry_count: int,
        recorded_transport: bool,
    ) -> PaidTestAttempt | None:
        if not self.enabled or recorded_transport or provider not in self.paid_providers:
            return None
        if self.level == TestExecutionLevel.LEVEL0:
            raise TestCostControlError("LEVEL0_PAID_PROVIDER_CALL_BLOCKED")
        configuration = self.validate_configuration()
        allowed = self._allowed_providers()
        if provider not in allowed:
            raise TestCostControlError(f"TEST_PROVIDER_NOT_ALLOWED:{provider}")
        affected_path = configuration["affected_path"]
        if (
            self.level == TestExecutionLevel.LEVEL1
            and provider == "kimi"
            and affected_path not in set(self.policy["kimi_level1_paths"])
        ):
            raise TestCostControlError("LEVEL1_KIMI_REQUIRES_PREMIUM_VISION_OR_COMPLEX_SCOPE")

        call_id = str(uuid4())
        now = datetime.now().astimezone()
        test_date = now.date().isoformat()
        run_id = self.environ["CHATBI_TEST_RUN_ID"].strip()
        max_requests_key = (
            "level1_max_real_provider_requests"
            if self.level == TestExecutionLevel.LEVEL1
            else "level2_max_real_provider_requests"
        )
        max_requests = int(self.policy["limits"][max_requests_key])
        run_budget = float(configuration["run_budget_cny"])
        daily_cap = float(configuration["daily_hard_cap_cny"])
        reserved = max(0.0, float(estimated_cost_cny))
        connection = self._connect(self._ledger_path())
        try:
            connection.execute("BEGIN IMMEDIATE")
            run_count, run_spend = connection.execute(
                """SELECT COUNT(*), COALESCE(SUM(MAX(reserved_cost_cny, actual_cost_cny)), 0)
                   FROM paid_test_calls WHERE test_run_id = ?""",
                (run_id,),
            ).fetchone()
            daily_spend = connection.execute(
                """SELECT COALESCE(SUM(MAX(reserved_cost_cny, actual_cost_cny)), 0)
                   FROM paid_test_calls WHERE test_date = ?""",
                (test_date,),
            ).fetchone()[0]
            if int(run_count) >= max_requests:
                raise TestCostControlError("MAX_REAL_PROVIDER_REQUESTS_EXCEEDED")
            if float(run_spend) + reserved > run_budget:
                raise TestCostControlError(
                    f"TEST_BUDGET_EXCEEDED REQUIRED_ESTIMATED_COST={float(run_spend) + reserved:.8f} "
                    f"REASON=run_hard_cap_{run_budget:.2f}"
                )
            if float(daily_spend) + reserved > daily_cap:
                raise TestCostControlError(
                    f"TEST_BUDGET_EXCEEDED REQUIRED_ESTIMATED_COST={float(daily_spend) + reserved:.8f} "
                    f"REASON=daily_hard_cap_{daily_cap:.2f}"
                )
            connection.execute(
                """INSERT INTO paid_test_calls (
                     call_id, test_date, test_run_id, tested_sha, case_id, gate_name,
                     provider, model, status, reserved_cost_cny, retry_count, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED', ?, ?, ?)""",
                (
                    call_id,
                    test_date,
                    run_id,
                    configuration["tested_sha"],
                    self.environ.get("CHATBI_TEST_CASE_ID") or context.request_id,
                    self.environ.get("CHATBI_TEST_GATE") or context.route or "unspecified",
                    provider,
                    model,
                    reserved,
                    max(0, retry_count),
                    now.isoformat(),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return PaidTestAttempt(call_id=call_id, provider=provider, model=model, retry_count=retry_count)

    def complete_attempt(
        self,
        attempt: PaidTestAttempt | None,
        *,
        status: str,
        response: ModelResponse | None = None,
        error_code: str | None = None,
    ) -> None:
        if attempt is None:
            return
        usage = response.usage if response is not None else None
        configuration = self.validate_configuration()
        connection = self._connect(self._ledger_path())
        exceeded: str | None = None
        try:
            connection.execute(
                """UPDATE paid_test_calls SET status = ?, input_tokens = ?, cached_input_tokens = ?,
                   output_tokens = ?, actual_cost_cny = ?, retry_count = ?, error_code = ?, completed_at = ?
                   WHERE call_id = ?""",
                (
                    status,
                    usage.input_tokens if usage else 0,
                    usage.cached_input_tokens if usage else 0,
                    usage.output_tokens if usage else 0,
                    response.cost_cny if response is not None else 0.0,
                    max(attempt.retry_count, response.retry_count if response is not None else 0),
                    error_code,
                    datetime.now().astimezone().isoformat(),
                    attempt.call_id,
                ),
            )
            test_date, run_id = connection.execute(
                "SELECT test_date, test_run_id FROM paid_test_calls WHERE call_id = ?",
                (attempt.call_id,),
            ).fetchone()
            run_spend = float(connection.execute(
                """SELECT COALESCE(SUM(MAX(reserved_cost_cny, actual_cost_cny)), 0)
                   FROM paid_test_calls WHERE test_run_id = ?""",
                (run_id,),
            ).fetchone()[0])
            daily_spend = float(connection.execute(
                """SELECT COALESCE(SUM(MAX(reserved_cost_cny, actual_cost_cny)), 0)
                   FROM paid_test_calls WHERE test_date = ?""",
                (test_date,),
            ).fetchone()[0])
            if run_spend > float(configuration["run_budget_cny"]):
                exceeded = (
                    f"TEST_BUDGET_EXCEEDED REQUIRED_ESTIMATED_COST={run_spend:.8f} "
                    f"REASON=actual_run_hard_cap_{float(configuration['run_budget_cny']):.2f}"
                )
            elif daily_spend > float(configuration["daily_hard_cap_cny"]):
                exceeded = (
                    f"TEST_BUDGET_EXCEEDED REQUIRED_ESTIMATED_COST={daily_spend:.8f} "
                    f"REASON=actual_daily_hard_cap_{float(configuration['daily_hard_cap_cny']):.2f}"
                )
        finally:
            connection.close()
        if exceeded:
            raise TestCostControlError(exceeded)

    def summary(self) -> dict[str, Any]:
        configuration = self.validate_configuration()
        if not self.enabled or self.level == TestExecutionLevel.LEVEL0:
            return {
                **configuration,
                "paid_test_calls": 0,
                "paid_test_cost_cny": 0.0,
                "cost_by_provider": {},
                "cost_by_gate": {},
                "budget_exceeded": False,
            }
        path = self._ledger_path()
        if not path.exists():
            return {
                **configuration,
                "paid_test_calls": 0,
                "paid_test_cost_cny": 0.0,
                "cost_by_provider": {},
                "cost_by_gate": {},
                "budget_exceeded": False,
            }
        connection = self._connect(path)
        try:
            run_id = self.environ["CHATBI_TEST_RUN_ID"].strip()
            rows = connection.execute(
                """SELECT provider, gate_name, actual_cost_cny, status, input_tokens,
                   cached_input_tokens, output_tokens, retry_count
                   FROM paid_test_calls WHERE test_run_id = ? ORDER BY created_at, call_id""",
                (run_id,),
            ).fetchall()
        finally:
            connection.close()
        by_provider: dict[str, float] = {}
        by_gate: dict[str, float] = {}
        for provider, gate, cost, *_ in rows:
            by_provider[provider] = round(by_provider.get(provider, 0.0) + float(cost), 8)
            by_gate[gate] = round(by_gate.get(gate, 0.0) + float(cost), 8)
        paid_cost = round(sum(float(row[2]) for row in rows), 8)
        return {
            **configuration,
            "paid_test_calls": len(rows),
            "paid_test_cost_cny": paid_cost,
            "cost_by_provider": by_provider,
            "cost_by_gate": by_gate,
            "input_tokens": sum(int(row[4]) for row in rows),
            "cached_input_tokens": sum(int(row[5]) for row in rows),
            "output_tokens": sum(int(row[6]) for row in rows),
            "retry_count": sum(int(row[7]) for row in rows),
            "budget_exceeded": paid_cost > float(configuration["run_budget_cny"]),
        }
