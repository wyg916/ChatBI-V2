from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text


DATABASE_ENV = "CHATBI_PHASE5_DATABASE_URL"

TABLE_GROUPS: dict[str, tuple[str, ...]] = {
    "auth": ("app_user", "resource_grant", "auth_session"),
    "chat": (
        "project", "conversation", "conversation_share", "chat_message",
        "attachment", "query_run", "query_feedback",
    ),
    "datasource": (
        "datasource", "datasource_schema", "datasource_table",
        "datasource_column", "datasource_relation",
    ),
    "semantic": (
        "semantic_model", "semantic_entity", "metric", "dimension",
        "semantic_relation", "business_term", "semantic_version",
    ),
    "answers": ("verified_answer", "answer_version"),
    "dashboards": ("dashboard", "dashboard_card"),
    "evaluation": ("evaluation_run", "evaluation_case_result"),
}

# Only non-secret state participates in fingerprints. In particular, password,
# token, connection and request payload columns are deliberately excluded.
SAFE_STATE_COLUMNS = {
    "id", "workspace_id", "user_id", "project_id", "conversation_id",
    "dashboard_id", "answer_id", "datasource_id", "schema_id", "table_id",
    "semantic_model_id", "evaluation_run_id", "name", "title", "status",
    "role", "type", "version", "is_current", "is_shared", "is_favorite",
    "pinned_at", "archived_at", "revoked_at", "published_at", "last_sync_at",
    "created_at", "updated_at", "completed_at", "card_count",
    "refresh_count_today", "sort_order", "accuracy_percent", "adoption_count",
    "monthly_adoption_count", "golden_set_count", "case_id", "execution_ok",
    "result_ok", "semantic_ok", "source_table", "primary_key", "time_dimension",
    "label", "aggregation", "source_column", "join_type", "cardinality",
    "resource_type", "resource_id", "can_read", "can_query", "access_count",
    "expires_at", "last_seen_at", "filename", "extension", "kind", "size_bytes",
    "query_run_id", "feedback_type", "provider", "error_code", "duration_ms",
}


def _sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _selected_columns(columns: list[dict[str, Any]]) -> list[str]:
    available = {str(column["name"]) for column in columns}
    selected = sorted(available & SAFE_STATE_COLUMNS)
    if "id" in available and "id" not in selected:
        selected.insert(0, "id")
    return selected


def snapshot(
    *, database_url: str, schema: str, group: str, workspace_id: str | None,
) -> dict[str, Any]:
    if group not in TABLE_GROUPS:
        raise ValueError(f"unknown probe group: {group}")
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    try:
        inspector = inspect(engine)
        preparer = engine.dialect.identifier_preparer
        existing = set(inspector.get_table_names(schema=schema))
        table_receipts: dict[str, Any] = {}
        with engine.connect() as connection:
            for table_name in TABLE_GROUPS[group]:
                if table_name not in existing:
                    table_receipts[table_name] = {"status": "MISSING"}
                    continue
                column_rows = inspector.get_columns(table_name, schema=schema)
                column_names = {str(column["name"]) for column in column_rows}
                selected = _selected_columns(column_rows)
                if not selected:
                    raise RuntimeError(f"no safe fingerprint columns for {table_name}")
                quoted_table = f"{preparer.quote(schema)}.{preparer.quote(table_name)}"
                expressions = ", ".join(
                    f"COALESCE({preparer.quote(column)}::text, '<NULL>')" for column in selected
                )
                row_expression = f"concat_ws('|', {expressions})"
                where = ""
                parameters: dict[str, Any] = {}
                if workspace_id and "workspace_id" in column_names:
                    where = f" WHERE {preparer.quote('workspace_id')} = :workspace_id"
                    parameters["workspace_id"] = workspace_id
                statement = text(
                    "SELECT COUNT(*) AS row_count, "
                    f"COALESCE(md5(string_agg(md5({row_expression}), '' "
                    f"ORDER BY md5({row_expression}))), md5('')) AS state_digest "
                    f"FROM {quoted_table}{where}"
                )
                row = connection.execute(statement, parameters).mappings().one()
                table_receipts[table_name] = {
                    "status": "PRESENT",
                    "row_count": int(row["row_count"]),
                    "state_digest": str(row["state_digest"]),
                    "fingerprint_columns": selected,
                    "workspace_scoped": bool(where),
                }
        payload = {
            "schema_version": "chatbi.v13.phase5.control-db-snapshot.v1",
            "group": group,
            "schema": schema,
            "workspace_scoped": bool(workspace_id),
            "tables": table_receipts,
            "secrets_exposed": False,
        }
        return {**payload, "fingerprint": _sha256(payload)}
    finally:
        engine.dispose()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a sanitized Phase5 control DB fingerprint")
    parser.add_argument("snapshot", nargs="?")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--group", choices=sorted(TABLE_GROUPS), required=True)
    parser.add_argument("--workspace-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    database_url = os.getenv(DATABASE_ENV, "")
    if not database_url:
        raise SystemExit(f"{DATABASE_ENV} is required")
    result = snapshot(
        database_url=database_url,
        schema=args.schema,
        group=args.group,
        workspace_id=args.workspace_id,
    )
    if args.output:
        _atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
