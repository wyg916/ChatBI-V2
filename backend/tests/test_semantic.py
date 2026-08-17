from app.models import DataSourceColumn, DataSourceSchema, DataSourceTable


def create_model(client, datasource_id):
    response = client.post("/api/v1/semantic-models", json={
        "name": "新能源经营分析",
        "description": "Day 1 semantic model",
        "datasource_id": datasource_id,
    })
    assert response.status_code == 201
    return response.json()["id"]


def prepare_catalog(db_session, datasource_id):
    schema = DataSourceSchema(datasource_id=datasource_id, name="public", qualified_name=f"{datasource_id}.public")
    db_session.add(schema)
    db_session.flush()
    definitions = {
        "orders": ["id", "order_date", "revenue", "region", "customer_id"],
        "customers": ["id"],
    }
    for table_name, columns in definitions.items():
        table = DataSourceTable(schema_id=schema.id, name=table_name, qualified_name=f"{schema.qualified_name}.{table_name}")
        db_session.add(table)
        db_session.flush()
        db_session.add_all([
            DataSourceColumn(
                table_id=table.id, name=column, qualified_name=f"{table.qualified_name}.{column}",
                data_type="TEXT", nullable=True,
            )
            for column in columns
        ])
    db_session.commit()


def test_semantic_model_crud(client, datasource_id):
    model_id = create_model(client, datasource_id)
    assert len(client.get("/api/v1/semantic-models").json()) == 1
    detail = client.get(f"/api/v1/semantic-models/{model_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "DRAFT"

    updated = client.put(f"/api/v1/semantic-models/{model_id}", json={"description": "Updated"})
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated"

    deleted = client.delete(f"/api/v1/semantic-models/{model_id}")
    assert deleted.status_code == 204


def test_semantic_children_and_publish(client, datasource_id, db_session):
    prepare_catalog(db_session, datasource_id)
    model_id = create_model(client, datasource_id)
    for entity in [
        {"name": "orders", "source_table": "orders", "primary_key": "id", "time_dimension": "order_date"},
        {"name": "customers", "source_table": "customers", "primary_key": "id"},
    ]:
        assert client.post(f"/api/v1/semantic-models/{model_id}/entities", json=entity).status_code == 201

    metric = {"name": "revenue", "label": "收入", "expression": "orders.revenue", "aggregation": "SUM", "filters": []}
    assert client.post(f"/api/v1/semantic-models/{model_id}/metrics", json=metric).status_code == 201

    dimension = {"name": "region", "label": "地区", "source_column": "orders.region", "type": "STRING"}
    assert client.post(f"/api/v1/semantic-models/{model_id}/dimensions", json=dimension).status_code == 201

    relation = {
        "left_entity": "orders",
        "right_entity": "customers",
        "join_type": "LEFT",
        "join_keys": [{"left": "customer_id", "right": "id"}],
        "cardinality": "MANY_TO_ONE",
    }
    assert client.post(f"/api/v1/semantic-models/{model_id}/relationships", json=relation).status_code == 201

    term = {"term": "收入", "synonyms": ["营收"], "definition": "订单收入总额", "mapped_object": "metric.revenue"}
    assert client.post(f"/api/v1/semantic-models/{model_id}/business-terms", json=term).status_code == 201

    detail = client.get(f"/api/v1/semantic-models/{model_id}").json()
    assert len(detail["entities"]) == 2
    assert len(detail["metrics"]) == 1
    assert len(detail["dimensions"]) == 1
    assert len(detail["relationships"]) == 1
    assert len(detail["business_terms"]) == 1

    listed = client.get("/api/v1/semantic-models").json()[0]
    assert len(listed["entities"]) == 2
    assert len(listed["metrics"]) == 1
    assert len(listed["relationships"]) == 1

    published = client.post(f"/api/v1/semantic-models/{model_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"
    assert published.json()["version"] == 1


def test_semantic_version_publish_history_and_rollback(client, datasource_id, db_session):
    prepare_catalog(db_session, datasource_id)
    model_id = create_model(client, datasource_id)
    client.post(f"/api/v1/semantic-models/{model_id}/entities", json={
        "name": "orders", "source_table": "orders", "primary_key": "id", "time_dimension": "order_date",
    })
    metric = client.post(f"/api/v1/semantic-models/{model_id}/metrics", json={
        "name": "revenue", "label": "收入 V1", "expression": "orders.revenue", "aggregation": "SUM", "filters": [],
    }).json()
    first = client.post(f"/api/v1/semantic-models/{model_id}/publish")
    assert first.status_code == 200 and first.json()["version"] == 1

    updated = client.put(f"/api/v1/semantic-models/{model_id}/metrics/{metric['id']}", json={
        "name": "revenue", "label": "收入 V2", "expression": "orders.revenue", "aggregation": "SUM", "filters": [],
    })
    assert updated.status_code == 200
    assert client.get(f"/api/v1/semantic-models/{model_id}").json()["status"] == "DRAFT"
    second = client.post(f"/api/v1/semantic-models/{model_id}/publish")
    assert second.status_code == 200 and second.json()["version"] == 2

    history = client.get(f"/api/v1/semantic-models/{model_id}/versions")
    assert history.status_code == 200
    assert [item["version"] for item in history.json()] == [2, 1]
    assert history.json()[0]["is_current"] is True

    rollback = client.post(f"/api/v1/semantic-models/{model_id}/versions/1/rollback")
    assert rollback.status_code == 200 and rollback.json()["version"] == 3
    detail = client.get(f"/api/v1/semantic-models/{model_id}").json()
    assert detail["status"] == "PUBLISHED"
    assert detail["version"] == 3
    assert detail["metrics"][0]["label"] == "收入 V1"
    history = client.get(f"/api/v1/semantic-models/{model_id}/versions").json()
    assert [item["version"] for item in history] == [3, 2, 1]
    assert history[0]["snapshot"]["rollback_source_version"] == 1


def test_publish_rejects_invalid_catalog_and_metric_dependency(client, datasource_id, db_session):
    prepare_catalog(db_session, datasource_id)
    model_id = create_model(client, datasource_id)
    client.post(f"/api/v1/semantic-models/{model_id}/entities", json={
        "name": "orders", "source_table": "orders", "primary_key": "missing_id", "time_dimension": "missing_date",
    })
    client.post(f"/api/v1/semantic-models/{model_id}/metrics", json={
        "name": "broken", "label": "无效指标", "expression": "orders.missing + unknown_metric", "aggregation": "SUM", "filters": [],
    })
    response = client.post(f"/api/v1/semantic-models/{model_id}/publish")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "unknown primary key" in detail
    assert "unknown time dimension" in detail
    assert "unknown column" in detail
    assert "invalid dependencies" in detail


def test_publish_rejects_unknown_relation_entity(client, datasource_id):
    model_id = create_model(client, datasource_id)
    relation = {
        "left_entity": "orders",
        "right_entity": "missing",
        "join_type": "LEFT",
        "join_keys": [{"left": "customer_id", "right": "id"}],
        "cardinality": "MANY_TO_ONE",
    }
    assert client.post(f"/api/v1/semantic-models/{model_id}/relationships", json=relation).status_code == 201
    response = client.post(f"/api/v1/semantic-models/{model_id}/publish")
    assert response.status_code == 422
    assert "Unknown" in response.json()["detail"]


def test_metric_dimension_relationship_resource_crud(client, datasource_id):
    model_id = create_model(client, datasource_id)
    metric = {"name": "revenue", "label": "收入", "expression": "orders.revenue", "aggregation": "SUM", "filters": []}
    metric_id = client.post(f"/api/v1/semantic-models/{model_id}/metrics", json=metric).json()["id"]
    metric["label"] = "营业收入"
    updated_metric = client.put(f"/api/v1/semantic-models/{model_id}/metrics/{metric_id}", json=metric)
    assert updated_metric.status_code == 200
    assert updated_metric.json()["label"] == "营业收入"

    dimension = {"name": "region", "label": "地区", "source_column": "orders.region", "type": "STRING"}
    dimension_id = client.post(f"/api/v1/semantic-models/{model_id}/dimensions", json=dimension).json()["id"]
    dimension["label"] = "经营区域"
    updated_dimension = client.put(f"/api/v1/semantic-models/{model_id}/dimensions/{dimension_id}", json=dimension)
    assert updated_dimension.status_code == 200
    assert updated_dimension.json()["label"] == "经营区域"

    relation = {
        "left_entity": "orders", "right_entity": "customers", "join_type": "LEFT",
        "join_keys": [{"left": "customer_id", "right": "id"}], "cardinality": "MANY_TO_ONE",
    }
    relation_id = client.post(f"/api/v1/semantic-models/{model_id}/relationships", json=relation).json()["id"]
    relation["join_type"] = "INNER"
    updated_relation = client.put(f"/api/v1/semantic-models/{model_id}/relationships/{relation_id}", json=relation)
    assert updated_relation.status_code == 200
    assert updated_relation.json()["join_type"] == "INNER"

    assert client.delete(f"/api/v1/semantic-models/{model_id}/metrics/{metric_id}").status_code == 204
    assert client.delete(f"/api/v1/semantic-models/{model_id}/dimensions/{dimension_id}").status_code == 204
    assert client.delete(f"/api/v1/semantic-models/{model_id}/relationships/{relation_id}").status_code == 204
    detail = client.get(f"/api/v1/semantic-models/{model_id}").json()
    assert detail["metrics"] == []
    assert detail["dimensions"] == []
    assert detail["relationships"] == []
