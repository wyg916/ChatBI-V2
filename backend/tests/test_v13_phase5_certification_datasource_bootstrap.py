from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.connectors.base import ColumnMetadata, ConnectorMetadata, TableMetadata
from app.certification.datasource_bootstrap import (
    DatasourceBootstrapError,
    bootstrap_certification_datasource,
)
from app.core.access import Principal, get_principal
from app.main import app
from app.models import AppUser


@dataclass
class FakeResponse:
    status_code: int
    payload: Any

    def json(self) -> Any:
        return self.payload


class BootstrapClient:
    def __init__(
        self,
        *,
        sync_counts: dict[str, int] | None = None,
        workspace_id: str = "workspace-certification",
        source_workspace_id: str | None = None,
        sources_available: bool = True,
        entity_table: str = "demo_business.orders",
    ) -> None:
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.sync_counts = sync_counts or {
            "schemas": 1,
            "tables": 1,
            "columns": 2,
            "relationships": 0,
        }
        self.workspace_id = workspace_id
        self.source_workspace_id = source_workspace_id or workspace_id
        self.sources_available = sources_available
        self.entity_table = entity_table

    def request(self, method: str, path: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, path, kwargs))
        if (method, path) == ("GET", "/auth/me"):
            return FakeResponse(200, {
                "authenticated": True,
                "user": {
                    "id": "user-certification",
                    "workspace_id": self.workspace_id,
                },
            })
        if (method, path) == ("GET", "/datasources"):
            return FakeResponse(200, [self._source()] if self.sources_available else [])
        if (method, path) == ("GET", "/semantic-models"):
            return FakeResponse(200, [self._model()] if self.sources_available else [])
        if (method, path) == ("GET", "/datasources/datasource-certification"):
            return FakeResponse(200, self._source())
        if (method, path) == ("GET", "/semantic-models/semantic-certification"):
            return FakeResponse(200, self._model(detail=True))
        if (method, path) == ("POST", "/datasources/datasource-certification/test"):
            return FakeResponse(200, {"success": True, "message": "Connection successful"})
        if (method, path) == ("POST", "/datasources/datasource-certification/sync"):
            return FakeResponse(200, {
                "success": True,
                "message": "Metadata synchronized",
                **self.sync_counts,
            })
        if (method, path) == ("GET", "/datasources/datasource-certification/schemas"):
            return FakeResponse(200, [{
                "id": "schema-certification",
                "name": "demo_business",
                "qualified_name": "datasource-certification.demo_business",
                "table_count": 1,
            }])
        if (method, path) == ("GET", "/datasources/datasource-certification/tables"):
            return FakeResponse(200, [{
                "id": "table-orders",
                "schema_name": "demo_business",
                "name": "orders",
                "qualified_name": "demo_business.orders",
                "comment": None,
                "column_count": 2,
            }])
        if (method, path) == (
            "GET", "/datasources/datasource-certification/tables/orders/columns"
        ):
            return FakeResponse(200, [
                {"id": "column-order-id", "name": "order_id"},
                {"id": "column-revenue", "name": "revenue"},
            ])
        raise AssertionError(f"unexpected request: {method} {path}")

    def _source(self) -> dict[str, Any]:
        return {
            "id": "datasource-certification",
            "workspace_id": self.source_workspace_id,
            "name": "Certification PostgreSQL",
            "type": "postgresql",
            "schema": "demo_business",
            "status": "SYNCED",
        }

    def _model(self, *, detail: bool = False) -> dict[str, Any]:
        model: dict[str, Any] = {
            "id": "semantic-certification",
            "workspace_id": self.source_workspace_id,
            "name": "Certification semantic model",
            "datasource_id": "datasource-certification",
            "status": "PUBLISHED",
            "version": 1,
        }
        if detail:
            model.update({
                "entities": [{
                    "id": "entity-orders",
                    "name": "orders",
                    "source_table": self.entity_table,
                    "primary_key": "order_id",
                }],
                "metrics": [],
                "dimensions": [],
                "relationships": [],
                "business_terms": [],
            })
        return model


def request_pairs(client: BootstrapClient) -> list[tuple[str, str]]:
    return [(method, path) for method, path, _ in client.requests]


def test_real_api_bootstrap_order_builds_catalog_allowlist_and_both_guard_gates() -> None:
    client = BootstrapClient()
    bindings = bootstrap_certification_datasource(client)

    assert bindings.datasource_id == "datasource-certification"
    assert bindings.semantic_model_id == "semantic-certification"
    assert bindings.receipt == {
        **bindings.receipt,
        "status": "PASS",
        "datasource_connectivity": "PASS",
        "schema_sync": "PASS",
        "catalog_sync": "PASS",
        "semantic_binding": "PASS",
        "datasource_workspace_binding": "PASS",
        "sql_guard_allowlist_count": 1,
        "expected_tables_authorized": "PASS",
        "allowlist_positive_gate": "PASS",
        "allowlist_negative_gate": "PASS",
        "cross_workspace_table_access": 0,
        "provider_call_allowed": True,
        "failures": [],
    }
    pairs = request_pairs(client)
    assert pairs.index(("POST", "/datasources/datasource-certification/test")) < pairs.index(
        ("POST", "/datasources/datasource-certification/sync")
    )
    assert pairs.index(("POST", "/datasources/datasource-certification/sync")) < pairs.index(
        ("GET", "/datasources/datasource-certification/schemas")
    )
    assert not any(path == "/chat" for _, path in pairs)


def test_skipping_sync_fails_before_catalog_or_provider_dispatch() -> None:
    client = BootstrapClient()
    with pytest.raises(
        DatasourceBootstrapError,
        match="DATASOURCE_SYNC_REQUIRED_BEFORE_PROVIDER",
    ) as captured:
        bootstrap_certification_datasource(client, perform_sync=False)

    assert captured.value.receipt["provider_call_allowed"] is False
    assert captured.value.receipt["schema_sync"] == "FAIL"
    pairs = request_pairs(client)
    assert ("POST", "/datasources/datasource-certification/test") in pairs
    assert ("POST", "/datasources/datasource-certification/sync") not in pairs
    assert not any(path == "/chat" for _, path in pairs)


@pytest.mark.parametrize(
    "sync_counts,error",
    (
        ({"schemas": 0, "tables": 0, "columns": 0, "relationships": 0}, "SCHEMA_SYNC_EMPTY"),
        ({"schemas": 1, "tables": 0, "columns": 0, "relationships": 0}, "CATALOG_SYNC_EMPTY"),
    ),
)
def test_empty_sync_fails_closed_before_provider(
    sync_counts: dict[str, int],
    error: str,
) -> None:
    client = BootstrapClient(sync_counts=sync_counts)
    with pytest.raises(DatasourceBootstrapError, match=error) as captured:
        bootstrap_certification_datasource(client)
    assert captured.value.receipt["provider_call_allowed"] is False
    assert not any(path == "/chat" for _, path in request_pairs(client))


def test_workspace_mismatch_fails_before_datasource_connection_test() -> None:
    client = BootstrapClient(source_workspace_id="other-workspace")
    with pytest.raises(
        DatasourceBootstrapError,
        match="CERTIFICATION_WORKSPACE_BINDING_MISMATCH",
    ) as captured:
        bootstrap_certification_datasource(client)
    assert captured.value.receipt["cross_workspace_table_access"] == 0
    assert ("POST", "/datasources/datasource-certification/test") not in request_pairs(client)


def test_missing_datasource_fails_before_connection_test_or_provider() -> None:
    client = BootstrapClient(sources_available=False)
    with pytest.raises(
        DatasourceBootstrapError,
        match="CERTIFICATION_DATASOURCE_NOT_FOUND",
    ) as captured:
        bootstrap_certification_datasource(client, datasource_id="missing-datasource")
    assert captured.value.receipt["provider_call_allowed"] is False
    assert not any(path.endswith("/test") or path == "/chat" for _, path in request_pairs(client))


def test_semantic_table_absent_from_synced_catalog_fails_closed() -> None:
    client = BootstrapClient(entity_table="demo_business.unauthorized_orders")
    with pytest.raises(
        DatasourceBootstrapError,
        match="SEMANTIC_EXPECTED_TABLE_NOT_AUTHORIZED",
    ) as captured:
        bootstrap_certification_datasource(client)
    assert captured.value.receipt["catalog_sync"] == "PASS"
    assert captured.value.receipt["allowlist_positive_gate"] == "FAIL"
    assert captured.value.receipt["provider_call_allowed"] is False


class FormalDatasourceConnector:
    def test_connection(self) -> None:
        return None

    def sync_metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            schemas=["demo_business"],
            tables=[
                TableMetadata(
                    schema="demo_business",
                    name="orders",
                    columns=[
                        ColumnMetadata(
                            name="order_id",
                            data_type="INTEGER",
                            nullable=False,
                            primary_key=True,
                        ),
                        ColumnMetadata(name="revenue", data_type="NUMERIC(12,2)"),
                    ],
                )
            ],
            relations=[],
        )


def test_bootstrap_uses_formal_authenticated_datasource_semantic_and_catalog_apis(
    client,
    db_session,
    datasource_payload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.datasources.build_connector",
        lambda _: FormalDatasourceConnector(),
    )
    admin = db_session.query(AppUser).filter_by(email="admin@chatbi.local").one()
    principal = Principal(
        admin.id,
        admin.workspace_id,
        admin.email,
        admin.display_name,
        admin.role,
        session_id="session-certification",
        session_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    app.dependency_overrides[get_principal] = lambda: principal

    datasource = client.post(
        "/api/v1/datasources",
        json={**datasource_payload, "schema": "demo_business"},
    )
    assert datasource.status_code == 201
    datasource_id = datasource.json()["id"]
    initial_sync = client.post(f"/api/v1/datasources/{datasource_id}/sync")
    assert initial_sync.status_code == 200 and initial_sync.json()["success"] is True

    model = client.post(
        "/api/v1/semantic-models",
        json={
            "name": "Certification semantic model",
            "description": "Harness-only binding verification",
            "datasource_id": datasource_id,
        },
    )
    assert model.status_code == 201
    model_id = model.json()["id"]
    entity = client.post(
        f"/api/v1/semantic-models/{model_id}/entities",
        json={
            "name": "orders",
            "source_table": "demo_business.orders",
            "primary_key": "order_id",
        },
    )
    metric = client.post(
        f"/api/v1/semantic-models/{model_id}/metrics",
        json={
            "name": "revenue",
            "label": "收入",
            "expression": "SUM(orders.revenue)",
            "aggregation": "SUM",
            "filters": [],
        },
    )
    assert entity.status_code == metric.status_code == 201
    published = client.post(f"/api/v1/semantic-models/{model_id}/publish")
    assert published.status_code == 200 and published.json()["status"] == "PUBLISHED"

    class ApiV1TestClient:
        def request(self, method: str, path: str, **kwargs: Any):
            return client.request(method, f"/api/v1{path}", **kwargs)

    bindings = bootstrap_certification_datasource(
        ApiV1TestClient(),
        datasource_id=datasource_id,
        semantic_model_id=model_id,
    )
    assert bindings.receipt["datasource_connectivity"] == "PASS"
    assert bindings.receipt["schema_sync"] == "PASS"
    assert bindings.receipt["catalog_sync"] == "PASS"
    assert bindings.receipt["semantic_binding"] == "PASS"
    assert bindings.receipt["sql_guard_allowlist_count"] == 1
    assert bindings.receipt["allowlist_positive_gate"] == "PASS"
    assert bindings.receipt["allowlist_negative_gate"] == "PASS"
