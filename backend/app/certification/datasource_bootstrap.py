from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from app.query.contracts import SecurityPolicy
from app.query.sql_guard import SqlGuard


class _Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


class CertificationHttpClient(Protocol):
    def request(self, method: str, path: str, **kwargs: Any) -> _Response: ...


class DatasourceBootstrapError(RuntimeError):
    """Fail-closed certification bootstrap error with a sanitized receipt."""

    def __init__(self, code: str, *, receipt: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.receipt = dict(receipt or {})


@dataclass(frozen=True)
class CertificationBindings:
    datasource_id: str
    semantic_model_id: str
    workspace_id: str
    user_id: str
    receipt: dict[str, Any]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_json(
    client: CertificationHttpClient,
    method: str,
    path: str,
    *,
    expected: Iterable[int],
    **kwargs: Any,
) -> Any:
    response = client.request(method, path, **kwargs)
    if response.status_code not in set(expected):
        raise DatasourceBootstrapError(
            f"BOOTSTRAP_HTTP_{response.status_code}:{method}:{path.split('?', 1)[0]}"
        )
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise DatasourceBootstrapError(
            f"BOOTSTRAP_INVALID_JSON:{method}:{path.split('?', 1)[0]}"
        ) from exc


def _selected_bindings(
    client: CertificationHttpClient,
    *,
    datasource_id: str | None,
    semantic_model_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    session = _request_json(client, "GET", "/auth/me", expected={200})
    if not isinstance(session, Mapping) or session.get("authenticated") is not True:
        raise DatasourceBootstrapError("CERTIFICATION_SESSION_NOT_AUTHENTICATED")
    user = session.get("user") or {}
    workspace_id = str(user.get("workspace_id") or "").strip()
    user_id = str(user.get("id") or "").strip()
    if not workspace_id or not user_id:
        raise DatasourceBootstrapError("CERTIFICATION_PRINCIPAL_BINDING_MISSING")

    sources = _request_json(client, "GET", "/datasources", expected={200})
    models = _request_json(client, "GET", "/semantic-models", expected={200})
    if not isinstance(sources, list) or not isinstance(models, list):
        raise DatasourceBootstrapError("CERTIFICATION_RESOURCE_LIST_INVALID")
    source_by_id = {
        str(item.get("id")): item for item in sources if isinstance(item, Mapping) and item.get("id")
    }
    model_by_id = {
        str(item.get("id")): item for item in models if isinstance(item, Mapping) and item.get("id")
    }
    if datasource_id:
        source = source_by_id.get(datasource_id)
        if source is None:
            raise DatasourceBootstrapError("CERTIFICATION_DATASOURCE_NOT_FOUND")
    else:
        source = None
    if semantic_model_id:
        model = model_by_id.get(semantic_model_id)
        if model is None:
            raise DatasourceBootstrapError("CERTIFICATION_SEMANTIC_MODEL_NOT_FOUND")
    else:
        candidates = [
            item for item in models
            if isinstance(item, Mapping) and str(item.get("status") or "").upper() == "PUBLISHED"
        ]
        model = next(
            (
                item for item in candidates
                if str(item.get("datasource_id") or "") in source_by_id
                and (source is None or str(item.get("datasource_id")) == str(source.get("id")))
            ),
            None,
        )
        if model is None:
            raise DatasourceBootstrapError("CERTIFICATION_PUBLISHED_BINDING_NOT_FOUND")
    bound_datasource_id = str(model.get("datasource_id") or "")
    if source is None:
        source = source_by_id.get(bound_datasource_id)
    if source is None or str(source.get("id") or "") != bound_datasource_id:
        raise DatasourceBootstrapError("CERTIFICATION_SEMANTIC_DATASOURCE_MISMATCH")

    source_workspace = str(source.get("workspace_id") or workspace_id)
    model_workspace = str(model.get("workspace_id") or workspace_id)
    if source_workspace != workspace_id or model_workspace != workspace_id:
        raise DatasourceBootstrapError("CERTIFICATION_WORKSPACE_BINDING_MISMATCH")

    source_detail = _request_json(
        client, "GET", f"/datasources/{source['id']}", expected={200}
    )
    model_detail = _request_json(
        client, "GET", f"/semantic-models/{model['id']}", expected={200}
    )
    if str(model_detail.get("datasource_id") or "") != str(source_detail.get("id") or ""):
        raise DatasourceBootstrapError("CERTIFICATION_SEMANTIC_DETAIL_BINDING_MISMATCH")
    if str(model_detail.get("status") or "").upper() != "PUBLISHED":
        raise DatasourceBootstrapError("CERTIFICATION_SEMANTIC_MODEL_NOT_PUBLISHED")
    return dict(source_detail), dict(model_detail), workspace_id, user_id


def _entity_tables(model: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for entity in model.get("entities") or []:
        if not isinstance(entity, Mapping):
            continue
        raw = str(entity.get("source_table") or "").strip().lower()
        if raw:
            values.add(raw.rsplit(".", 1)[-1])
    return values


def bootstrap_certification_datasource(
    client: CertificationHttpClient,
    *,
    datasource_id: str | None = None,
    semantic_model_id: str | None = None,
    perform_sync: bool = True,
) -> CertificationBindings:
    """Prepare the real datasource catalog before any certification Provider call.

    The function only uses authenticated product APIs for datasource testing,
    synchronization and catalog reads. It never creates an allowlist or inserts
    catalog rows directly. Any incomplete precondition raises before the caller
    may dispatch a chat/Provider request.
    """

    receipt: dict[str, Any] = {
        "schema_version": "chatbi-v1.3-final-certification-datasource-bootstrap-v1",
        "status": "FAIL",
        "datasource_connectivity": "FAIL",
        "schema_sync": "FAIL",
        "catalog_sync": "FAIL",
        "semantic_binding": "FAIL",
        "datasource_workspace_binding": "FAIL",
        "sql_guard_allowlist_count": 0,
        "expected_tables_authorized": "FAIL",
        "allowlist_positive_gate": "FAIL",
        "allowlist_negative_gate": "FAIL",
        "cross_workspace_table_access": 0,
        "provider_call_allowed": False,
        "failures": [],
    }

    def fail(code: str) -> None:
        receipt["failures"].append(code)
        raise DatasourceBootstrapError(code, receipt=receipt)

    try:
        source, model, workspace_id, user_id = _selected_bindings(
            client,
            datasource_id=datasource_id,
            semantic_model_id=semantic_model_id,
        )
        receipt["datasource_id_sha256"] = _sha256(str(source["id"]))
        receipt["semantic_model_id_sha256"] = _sha256(str(model["id"]))
        receipt["workspace_id_sha256"] = _sha256(workspace_id)
        receipt["user_id_sha256"] = _sha256(user_id)
        receipt["semantic_binding"] = "PASS"
        receipt["datasource_workspace_binding"] = "PASS"

        connection = _request_json(
            client, "POST", f"/datasources/{source['id']}/test", expected={200}
        )
        if not isinstance(connection, Mapping) or connection.get("success") is not True:
            fail("DATASOURCE_CONNECTIVITY_FAILED")
        receipt["datasource_connectivity"] = "PASS"

        if not perform_sync:
            fail("DATASOURCE_SYNC_REQUIRED_BEFORE_PROVIDER")
        sync = _request_json(
            client, "POST", f"/datasources/{source['id']}/sync", expected={200}
        )
        if not isinstance(sync, Mapping) or sync.get("success") is not True:
            fail("DATASOURCE_SYNC_FAILED")
        if int(sync.get("schemas") or 0) <= 0:
            fail("SCHEMA_SYNC_EMPTY")
        receipt["schema_sync"] = "PASS"
        if int(sync.get("tables") or 0) <= 0 or int(sync.get("columns") or 0) <= 0:
            fail("CATALOG_SYNC_EMPTY")

        schemas = _request_json(
            client, "GET", f"/datasources/{source['id']}/schemas", expected={200}
        )
        if not isinstance(schemas, list) or not schemas:
            fail("CATALOG_SCHEMA_READ_EMPTY")
        tables: list[dict[str, Any]] = []
        columns: dict[str, list[str]] = {}
        schema_names: set[str] = set()
        for schema in schemas:
            if not isinstance(schema, Mapping) or not schema.get("name"):
                fail("CATALOG_SCHEMA_INVALID")
            schema_name = str(schema["name"]).lower()
            schema_names.add(schema_name)
            rows = _request_json(
                client,
                "GET",
                f"/datasources/{source['id']}/tables",
                expected={200},
                params={"schema": schema["name"]},
            )
            if not isinstance(rows, list):
                fail("CATALOG_TABLE_READ_INVALID")
            for table in rows:
                if not isinstance(table, Mapping) or not table.get("name"):
                    fail("CATALOG_TABLE_INVALID")
                table_name = str(table["name"]).lower()
                tables.append(dict(table))
                column_rows = _request_json(
                    client,
                    "GET",
                    f"/datasources/{source['id']}/tables/{table['name']}/columns",
                    expected={200},
                    params={"schema": schema["name"]},
                )
                if not isinstance(column_rows, list) or not column_rows:
                    fail("CATALOG_COLUMN_READ_EMPTY")
                columns.setdefault(table_name, []).extend(
                    str(item.get("name") or "").lower()
                    for item in column_rows
                    if isinstance(item, Mapping) and item.get("name")
                )
        table_names = {str(item["name"]).lower() for item in tables}
        if len(table_names) < int(sync.get("tables") or 0) or not all(columns.values()):
            fail("CATALOG_READBACK_INCOMPLETE")
        receipt["catalog_sync"] = "PASS"
        receipt["sql_guard_allowlist_count"] = len(table_names)

        expected_tables = _entity_tables(model)
        if not expected_tables or not expected_tables <= table_names:
            fail("SEMANTIC_EXPECTED_TABLE_NOT_AUTHORIZED")
        receipt["expected_tables_authorized"] = "PASS"
        policy = SecurityPolicy(
            allowed_schemas=sorted(schema_names),
            allowed_tables=sorted(table_names),
            allowed_columns={key: sorted(set(value)) for key, value in columns.items()},
            row_limit=1,
        )
        positive_table = sorted(expected_tables)[0]
        positive_columns = policy.allowed_columns.get(positive_table) or []
        if not positive_columns:
            fail("SEMANTIC_EXPECTED_TABLE_COLUMNS_EMPTY")
        positive = SqlGuard().validate(
            f'SELECT "{positive_columns[0]}" FROM "{positive_table}" LIMIT 1',
            dialect=str(source.get("type") or "postgresql"),
            policy=policy,
        )
        if not positive.allowed:
            fail("ALLOWLIST_POSITIVE_GATE_FAILED")
        receipt["allowlist_positive_gate"] = "PASS"

        negative = SqlGuard().validate(
            'SELECT 1 FROM "__chatbi_certification_unauthorized__"',
            dialect=str(source.get("type") or "postgresql"),
            policy=policy,
        )
        negative_codes = {item.code for item in negative.issues}
        if negative.allowed or "TABLE_NOT_AUTHORIZED" not in negative_codes:
            fail("ALLOWLIST_NEGATIVE_GATE_FAILED")
        receipt["allowlist_negative_gate"] = "PASS"
        receipt["status"] = "PASS"
        receipt["provider_call_allowed"] = True
        return CertificationBindings(
            datasource_id=str(source["id"]),
            semantic_model_id=str(model["id"]),
            workspace_id=workspace_id,
            user_id=user_id,
            receipt=receipt,
        )
    except DatasourceBootstrapError as exc:
        if not exc.receipt:
            receipt["failures"].append(exc.code)
            exc.receipt = receipt
        raise
