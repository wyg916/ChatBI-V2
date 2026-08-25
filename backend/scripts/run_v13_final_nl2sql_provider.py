from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx

from app.certification.datasource_bootstrap import (
    DatasourceBootstrapError,
    bootstrap_certification_datasource,
)
from app.certification.runtime_binding import (
    RuntimeBindingError,
    run_exact_sha_runtime_preflight,
    seal_runtime_preflight_receipt,
)
from app.model_gateway.test_cost_control import TestCostController, TestExecutionLevel
from run_v13_phase5_live_questions_gate import (
    _analysis_primary,
    _answer_oracle,
    _answer_status,
    _answer_text,
    _first_mapping,
    _ledger_for_request,
    _request_json,
    _route,
    _trace_evidence,
    _trace_id,
    _verification_evidence,
    load_external_credentials,
    sha256_text,
    validate_backend_url,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
QUESTION = "统计全部订单收入"
EXPECTED_ROWS = [{"revenue": 1725750.0}]


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _case_provider(case_id: str) -> str:
    suffix = case_id.rsplit("-", 1)[-1].lower()
    return suffix if suffix in {"mimo", "deepseek", "deterministic"} else ""


def _paid_identity(
    client: httpx.Client,
    *,
    provider: str,
    expected_sha: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    controller = TestCostController()
    configuration = controller.validate_configuration()
    identity = controller.runtime_identity()
    if controller.level != TestExecutionLevel.FINAL or not configuration.get("paid_calls_allowed"):
        raise RuntimeError("FINAL_PAID_TEST_LEVEL_REQUIRED")
    if identity.get("tested_sha") != expected_sha:
        raise RuntimeError("PAID_RUNTIME_TESTED_SHA_MISMATCH")
    backend_identity = _request_json(
        client, "GET", "/test-cost-control-status", expected={200}
    )
    checked = (
        "enabled",
        "level",
        "paid_calls_allowed",
        "tested_sha",
        "backend_sha",
        "config_hash",
        "prompt_version",
        "ledger_identity",
        "test_run_id",
        "gate",
    )
    mismatches = [name for name in checked if backend_identity.get(name) != identity.get(name)]
    if mismatches:
        raise RuntimeError("BACKEND_COST_CONTROL_IDENTITY_MISMATCH:" + ",".join(mismatches))
    plan = configuration.get("final_provider_execution_plan") or {}
    provider_caps = plan.get("provider_call_caps") or {}
    allowed_providers = {
        value.strip().lower()
        for value in os.environ.get("CHATBI_TEST_ALLOWED_PROVIDERS", "").split(",")
        if value.strip()
    }
    if int(provider_caps.get(provider) or 0) <= 0 or provider not in allowed_providers:
        raise RuntimeError("FINAL_PROVIDER_CAP_PREFLIGHT_FAILED")
    return identity, backend_identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--provider", choices=("deterministic", "mimo", "deepseek"), required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--datasource-id")
    parser.add_argument("--semantic-model-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    expected_sha = args.expected_sha.strip().lower()
    if not _FULL_SHA.fullmatch(expected_sha):
        raise SystemExit("EXPECTED_SHA_INVALID")
    if _case_provider(args.case_id) != args.provider:
        raise SystemExit("CASE_PROVIDER_MISMATCH")

    result: dict[str, Any] = {
        "schema_version": "chatbi-phase5-final-nl2sql-full-chain-v2",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tested_sha": expected_sha,
        "case_id": args.case_id,
        "provider": args.provider,
        "question_sha256": hashlib.sha256(QUESTION.encode()).hexdigest(),
        "provider_call_dispatched": False,
        "failures": [],
    }
    conversation_id: str | None = None
    try:
        result["exact_sha_runtime_preflight"] = seal_runtime_preflight_receipt(
            run_exact_sha_runtime_preflight(
                repo_root=REPO_ROOT,
                expected_git_sha=expected_sha,
            )
        )
        credentials = load_external_credentials(args.env_file, allow_bootstrap_admin=True)
        api_base = validate_backend_url(args.api_base)
        with httpx.Client(
            base_url=api_base,
            timeout=httpx.Timeout(90),
            trust_env=False,
        ) as client:
            login = _request_json(
                client,
                "POST",
                "/auth/login",
                expected={200},
                json={**credentials, "remember": False},
            )
            result["authenticated"] = login.get("authenticated") is True
            try:
                bindings = bootstrap_certification_datasource(
                    client,
                    datasource_id=args.datasource_id,
                    semantic_model_id=args.semantic_model_id,
                )
                result["datasource_bootstrap"] = bindings.receipt
                result["binding"] = {
                    "datasource_id_sha256": sha256_text(bindings.datasource_id),
                    "semantic_model_id_sha256": sha256_text(bindings.semantic_model_id),
                    "workspace_id_sha256": sha256_text(bindings.workspace_id),
                    "user_id_sha256": sha256_text(bindings.user_id),
                }
                if args.provider == "deterministic":
                    result["cost_provider_cap_preflight"] = "NOT_APPLICABLE_ZERO_PAID"
                    result["runtime_identity"] = {
                        "tested_sha": expected_sha,
                        "level": "LEVEL0",
                        "paid_calls_allowed": False,
                    }
                else:
                    identity, backend_identity = _paid_identity(
                        client,
                        provider=args.provider,
                        expected_sha=expected_sha,
                    )
                    result["runtime_identity"] = identity
                    result["backend_runtime_identity"] = backend_identity
                    result["cost_provider_cap_preflight"] = "PASS"

                conversation = _request_json(
                    client,
                    "POST",
                    "/conversations",
                    expected={201},
                    json={"title": f"Phase5 final {args.provider} NL2SQL"},
                )
                conversation_id = str(conversation["id"])
                result["provider_call_dispatched"] = args.provider != "deterministic"
                response_payload = _request_json(
                    client,
                    "POST",
                    "/chat",
                    expected={201},
                    json={
                        "conversation_id": conversation_id,
                        "client_message_id": args.case_id,
                        "content": QUESTION,
                        "route": "DATA_QUERY",
                        "datasource_id": bindings.datasource_id,
                        "semantic_model_id": bindings.semantic_model_id,
                    },
                )
                trace_id = _trace_id(response_payload)
                route = _route(response_payload)
                trace = _trace_evidence(client, trace_id)
                verification = _verification_evidence(response_payload)
                primary = _analysis_primary(response_payload)
                result_evidence = _first_mapping(primary, "result_evidence")
                actual_rows = (
                    result_evidence.get("rows")
                    if isinstance(result_evidence.get("rows"), list)
                    else None
                )
                answer_oracle = _answer_oracle(response_payload, verification)
                result.update(
                    {
                        "route": route,
                        "assistant_status": _answer_status(response_payload),
                        "result_semantic": response_payload.get("result_semantic"),
                        "trace_id": trace_id,
                        "trace": trace,
                        "verification": verification,
                        "answer_oracle": answer_oracle,
                        "actual_rows_sha256": (
                            sha256_text(json.dumps(actual_rows, ensure_ascii=False, sort_keys=True))
                            if actual_rows is not None
                            else None
                        ),
                        "expected_rows_sha256": sha256_text(
                            json.dumps(EXPECTED_ROWS, ensure_ascii=False, sort_keys=True)
                        ),
                        "sql_sha256": sha256_text(
                            str(result_evidence.get("sql") or primary.get("sql") or "")
                        ),
                        "answer_text_sha256": sha256_text(_answer_text(response_payload)),
                    }
                )
                failures = result["failures"]
                if route != "DATA_QUERY":
                    failures.append("route_not_data_query")
                if _answer_status(response_payload) != "SUCCEEDED":
                    failures.append("assistant_not_succeeded")
                if actual_rows != EXPECTED_ROWS:
                    failures.append("independent_exact_value_mismatch")
                if not verification.get("self_reported_result_verified"):
                    failures.append("result_oracle_not_verified")
                if not trace.get("trace_id_exact") or not trace.get("has_sql"):
                    failures.append("query_executor_trace_missing")
                if not answer_oracle.get("answer_present") or not answer_oracle.get(
                    "numeric_claim_present"
                ):
                    failures.append("verified_answer_missing")
                if args.provider != "deterministic":
                    ledger = _ledger_for_request(
                        client,
                        conversation_id=conversation_id,
                        request_id=args.case_id,
                    )
                    result["ledger"] = ledger
                    if (
                        ledger.get("coverage_source") != "MODEL_INVOCATION_LEDGER"
                        or not ledger.get("coverage_complete")
                    ):
                        failures.append("ledger_coverage_incomplete")
                    if ledger.get("invocation_count") != 1:
                        failures.append("provider_call_count_not_one")
                    if ledger.get("providers") != [args.provider]:
                        failures.append("provider_binding_mismatch")
                    if any(status != "SUCCEEDED" for status in ledger.get("statuses") or []):
                        failures.append("ledger_invocation_not_succeeded")
            except DatasourceBootstrapError as exc:
                result["datasource_bootstrap"] = exc.receipt
                result["failures"].append(f"bootstrap:{exc.code}")
            finally:
                if conversation_id:
                    deleted = client.delete(f"/conversations/{conversation_id}")
                    absent = client.get(f"/conversations/{conversation_id}")
                    result["cleanup"] = {
                        "delete_status": deleted.status_code,
                        "absence_status": absent.status_code,
                        "verified": deleted.status_code == 204 and absent.status_code == 404,
                    }
                    if not result["cleanup"]["verified"]:
                        result["failures"].append("conversation_cleanup_failed")
                logout = client.post("/auth/logout")
                result["logout_status"] = logout.status_code
                if logout.status_code != 204:
                    result["failures"].append("logout_failed")
    except RuntimeBindingError as exc:
        result["exact_sha_runtime_preflight"] = exc.receipt
        result["failures"].append(f"runtime_binding:{type(exc).__name__}")
    except Exception as exc:
        result["failures"].append(f"runtime:{type(exc).__name__}:{str(exc)[:300]}")

    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["status"] = "PASS" if not result["failures"] else "FAIL"
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    for secret_name in (
        "CHATBI_PHASE5_PASSWORD",
        "CHATBI_BOOTSTRAP_ADMIN_PASSWORD",
        "CHATBI_MIMO_API_KEY",
        "CHATBI_DEEPSEEK_API_KEY",
    ):
        secret = os.environ.get(secret_name, "")
        if secret and secret in serialized:
            raise SystemExit("SECRET_LEAK_IN_EVIDENCE")
    _atomic_json(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "tested_sha": expected_sha,
                "case_id": args.case_id,
                "provider": args.provider,
                "provider_call_dispatched": result["provider_call_dispatched"],
                "failures": result["failures"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
