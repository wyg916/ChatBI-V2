from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any


def _split_dataframe(rows: list[dict[str, Any]], columns: list[str]) -> str:
    # IBM parse_dataframe accepts the exact string returned by
    # pandas.DataFrame.to_json(orient="split"), not the decoded object.
    return json.dumps(
        {
            "columns": columns,
            "index": list(range(len(rows))),
            "data": [[row.get(column) for column in columns] for row in rows],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _load_selected_source(checkout: Path):
    package_root = checkout / "src" / "text2sql_eval_toolkit"
    package = types.ModuleType("text2sql_eval_toolkit")
    package.__path__ = [str(package_root)]
    sys.modules["text2sql_eval_toolkit"] = package
    evaluation = importlib.import_module("text2sql_eval_toolkit.evaluation.evaluation_tools")
    analysis = importlib.import_module("text2sql_eval_toolkit.analysis.error_analysis")
    return evaluation, analysis


def diagnostic_category(result: dict[str, Any]) -> str | None:
    if (
        int(result.get("execution_accuracy") or 0) == 1
        and int(result.get("subset_non_empty_execution_accuracy") or 0) == 0
    ):
        return "EMPTY_RESULT_POLICY_DIAGNOSTIC_NOT_APPLICABLE"
    if int(result.get("execution_accuracy") or 0) == 0:
        return "RESULT_MISMATCH"
    return None


def run(checkout: Path, cases: list[dict[str, Any]]) -> dict[str, Any]:
    evaluation, analysis = _load_selected_source(checkout)
    outcomes: list[dict[str, Any]] = []
    official_records: list[dict[str, Any]] = []
    error_counts: Counter[str] = Counter()
    diagnostic_counts: Counter[str] = Counter()
    multiple_ground_truth = False
    for case in cases:
        truths = case["ground_truths"]
        multiple_ground_truth = multiple_ground_truth or len(truths) > 1
        record = {
            "id": case["id"],
            "question": case.get("question", ""),
            "sql": [truth["sql"] for truth in truths],
            "gt_df": [
                _split_dataframe(truth["rows"], truth["columns"])
                for truth in truths
            ],
        }
        prediction = {
            "predicted_sql": case["predicted_sql"],
            "predicted_df": _split_dataframe(case["predicted_rows"], case["predicted_columns"]),
        }
        result = evaluation.evaluate_prediction(record, prediction)
        if result.get("df_error"):
            error_counts["DATAFRAME_ERROR"] += 1
        if result.get("eval_error"):
            error_counts["EVALUATION_ERROR"] += 1
        if not result.get("execution_accuracy"):
            error_counts["RESULT_MISMATCH"] += 1
        diagnostic = diagnostic_category(result)
        if diagnostic:
            diagnostic_counts[diagnostic] += 1
        outcomes.append(
            {
                "id": case["id"],
                "execution_accuracy": int(result.get("execution_accuracy") or 0),
                "subset_non_empty_execution_accuracy": int(
                    result.get("subset_non_empty_execution_accuracy") or 0
                ),
                "df_error": int(result.get("df_error") or 0),
                "eval_error": int(result.get("eval_error") or 0),
                "diagnostic": diagnostic,
                "matched_ground_truth_sql_sha256": (
                    hashlib.sha256(result["gt_sql"].encode("utf-8")).hexdigest()
                    if result.get("gt_sql")
                    else None
                ),
            }
        )
        official_records.append({"id": case["id"], "predictions": {"chatbi": {"evaluation": result}}})
    official_failures = analysis.get_failed_records(
        official_records, "chatbi", metric="execution_accuracy"
    )
    execution_passed = sum(item["execution_accuracy"] for item in outcomes)
    non_empty_subset_passed = sum(
        item["subset_non_empty_execution_accuracy"] for item in outcomes
    )
    return {
        "official_tool_executed": True,
        "implementation_origin": "ibm-selected-source",
        "runtime_module": str(Path(evaluation.__file__).relative_to(checkout)).replace("\\", "/"),
        "error_analysis_module": str(Path(analysis.__file__).relative_to(checkout)).replace("\\", "/"),
        "runtime_function": "text2sql_eval_toolkit.evaluation.evaluation_tools.evaluate_prediction",
        "error_analysis_function": "text2sql_eval_toolkit.analysis.error_analysis.get_failed_records",
        "runtime_calls": len(outcomes),
        "tool_executions": 1,
        "case_count": len(outcomes),
        "multiple_ground_truth": multiple_ground_truth,
        "execution_compare": "PASS" if execution_passed == len(outcomes) else "FAIL",
        "result_value_accuracy": execution_passed / len(outcomes) if outcomes else 0.0,
        "subset_non_empty_execution_accuracy": (
            non_empty_subset_passed / len(outcomes) if outcomes else 0.0
        ),
        "error_analysis": "PASS",
        "official_error_count": len(official_failures),
        "error_counts": dict(sorted(error_counts.items())),
        "diagnostic_counts": dict(sorted(diagnostic_counts.items())),
        "cases": outcomes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = run(args.checkout.resolve(), payload["cases"])
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
