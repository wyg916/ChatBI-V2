from app.connectors.base import ColumnMetadata, ConnectorMetadata, RelationMetadata, TableMetadata


class FakeConnector:
    def test_connection(self):
        return None

    def sync_metadata(self):
        return ConnectorMetadata(
            schemas=["public"],
            tables=[
                TableMetadata(schema="public", name="customers", columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", nullable=False, primary_key=True),
                    ColumnMetadata(name="name", data_type="VARCHAR(255)"),
                ]),
                TableMetadata(schema="public", name="orders", columns=[
                    ColumnMetadata(name="id", data_type="INTEGER", nullable=False, primary_key=True),
                    ColumnMetadata(name="customer_id", data_type="INTEGER", foreign_key=True),
                    ColumnMetadata(name="revenue", data_type="NUMERIC(12,2)"),
                ]),
            ],
            relations=[RelationMetadata(
                source_schema="public",
                source_table="orders",
                source_columns=["customer_id"],
                target_schema="public",
                target_table="customers",
                target_columns=["id"],
            )],
        )


def test_datasource_crud_hides_password(client, datasource_payload):
    created = client.post("/api/v1/datasources", json=datasource_payload)
    assert created.status_code == 201
    body = created.json()
    assert "password" not in body
    assert "password_encrypted" not in body

    datasource_id = body["id"]
    listed = client.get("/api/v1/datasources")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.put(f"/api/v1/datasources/{datasource_id}", json={"name": "Renamed"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"

    deleted = client.delete(f"/api/v1/datasources/{datasource_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/datasources/{datasource_id}").status_code == 404


def test_connection_test(client, datasource_id, monkeypatch):
    monkeypatch.setattr("app.services.datasources.build_connector", lambda _: FakeConnector())
    response = client.post(f"/api/v1/datasources/{datasource_id}/test")
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Connection successful",
        "schemas": None,
        "tables": None,
        "columns": None,
        "relationships": None,
    }


def test_schema_sync_and_metadata_catalog(client, datasource_id, monkeypatch):
    monkeypatch.setattr("app.services.datasources.build_connector", lambda _: FakeConnector())
    response = client.post(f"/api/v1/datasources/{datasource_id}/sync")
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["schemas"] == 1
    assert response.json()["tables"] == 2
    assert response.json()["columns"] == 5
    assert response.json()["relationships"] == 1

    schemas = client.get(f"/api/v1/datasources/{datasource_id}/schemas").json()
    assert schemas[0]["qualified_name"] == f"{datasource_id}.public"
    assert schemas[0]["table_count"] == 2

    tables = client.get(f"/api/v1/datasources/{datasource_id}/tables?schema=public").json()
    assert {item["name"] for item in tables} == {"customers", "orders"}
    assert {item["name"]: item["column_count"] for item in tables} == {"customers": 2, "orders": 3}

    columns = client.get(f"/api/v1/datasources/{datasource_id}/tables/orders/columns?schema=public").json()
    assert len(columns) == 3
    assert all(item["qualified_name"].startswith(f"{datasource_id}.public.orders.") for item in columns)

    detail = client.get(f"/api/v1/datasources/{datasource_id}").json()
    assert detail["table_count"] == 2
    assert detail["column_count"] == 5

    listed = client.get("/api/v1/datasources").json()
    assert listed[0]["table_count"] == 2
    assert listed[0]["column_count"] == 5

    updated = client.put(f"/api/v1/datasources/{datasource_id}", json={"name": "Updated catalog"}).json()
    assert updated["table_count"] == 2
    assert updated["column_count"] == 5


def test_connection_failure_is_sanitized(client, datasource_id, monkeypatch):
    class BrokenConnector(FakeConnector):
        def test_connection(self):
            raise RuntimeError("password=safe-test-password")

    monkeypatch.setattr("app.services.datasources.build_connector", lambda _: BrokenConnector())
    response = client.post(f"/api/v1/datasources/{datasource_id}/test")
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert "safe-test-password" not in response.text
