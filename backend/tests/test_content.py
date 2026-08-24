from app.models import AuditEvent, Dashboard
from app.services.seed import seed_demo_semantic_model


def test_answer_library_is_database_backed_and_summary_is_derived(client, db_session):
    seed_demo_semantic_model(db_session)

    response = client.get("/api/v1/answers")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "total": 128,
        "average_accuracy": 96.4,
        "monthly_adoptions": 1284,
        "pending_review": 14,
        "favorites": 128,
        "drafts": 14,
        "published": 0,
        "verified": 0,
        "rejected": 0,
        "deprecated": 114,
    }
    assert payload["total"] == 128
    assert len(payload["items"]) == 6
    assert payload["items"][0]["question"] == "2026年二季度环比增长率入围多少?"

    drafts = client.get("/api/v1/answers", params={"tab": "drafts", "query": "退款"})
    assert drafts.status_code == 200
    assert drafts.json()["total"] == 1
    assert drafts.json()["items"][0]["status"] == "DRAFT"
    review = client.get("/api/v1/answers", params={"tab": "review"})
    assert review.status_code == 200
    assert review.json()["total"] == 14
    assert all(item["status"] == "DRAFT" for item in review.json()["items"])


def test_answer_create_persists_through_api(client):
    response = client.post("/api/v1/answers", json={
        "question": "近 12 个月订单量是多少？",
        "model_name": "订单量",
        "owner_name": "数据分析组",
        "status": "DRAFT",
        "accuracy_percent": 0,
    })
    assert response.status_code == 201
    assert response.json()["sql_synced"] is False

    listed = client.get("/api/v1/answers", params={"query": "订单量是多少"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_dashboard_library_summary_and_create_are_database_backed(client, db_session):
    seed_demo_semantic_model(db_session)

    response = client.get("/api/v1/dashboards")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {"total": 18, "cards": 0, "shared": 9, "refreshes_today": 0}
    assert len(payload["items"]) == 6

    created = client.post("/api/v1/dashboards", json={
        "name": "订单质量看板",
        "description": "订单异常与退款趋势",
        "is_shared": True,
    })
    assert created.status_code == 201
    stored = db_session.get(Dashboard, created.json()["id"])
    stored.card_count = 99
    stored.refresh_count_today = 88
    db_session.add(AuditEvent(
        workspace_id=stored.workspace_id,
        actor_email="admin@chatbi.local",
        action="REFRESH_CARD",
        resource_type="DASHBOARD",
        resource_id=stored.id,
        status="SUCCESS",
        details={},
    ))
    db_session.commit()

    listed = client.get("/api/v1/dashboards", params={"query": "订单质量"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["card_count"] == 0
    assert listed.json()["items"][0]["refresh_count_today"] == 1
    assert client.get("/api/v1/dashboards").json()["summary"]["refreshes_today"] == 1

    rejected_fake_count = client.post("/api/v1/dashboards", json={
        "name": "伪造卡片数看板",
        "description": "客户端不得提交派生卡片数",
        "card_count": 3,
    })
    assert rejected_fake_count.status_code == 422


def test_dashboard_detail_uses_backend_business_snapshot(client, db_session, monkeypatch):
    seed_demo_semantic_model(db_session)
    dashboard = client.get("/api/v1/dashboards").json()["items"][0]

    def snapshot(_, dashboard_model, __):
        return {
            "dashboard": dashboard_model,
            "data_as_of": "2026-08-17",
            "range_start": "2026-07-19",
            "range_end": "2026-08-17",
            "kpis": [{"label": "总收入", "value": 18420000, "unit": "元", "change": 12.3, "change_unit": "%"}],
            "revenue_trend": [{"date": "2026-08-17", "revenue": 320000}],
            "regions": [{"region": "华东", "order_count": 956, "revenue": 3663500, "charging_kwh": 82648, "margin_percent": 12.8, "change_percent": 8.6}],
            "insight": "华东收入领先。",
        }

    monkeypatch.setattr("app.api.routes.content.dashboard_detail", snapshot)
    response = client.get(f"/api/v1/dashboards/{dashboard['id']}")
    assert response.status_code == 200
    assert response.json()["dashboard"]["name"] == "经营总览看板"
    assert response.json()["regions"][0]["region"] == "华东"


def test_evaluation_overview_is_database_backed(client, db_session):
    seed_demo_semantic_model(db_session)
    response = client.get("/api/v1/evaluation/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["current"]["release_name"] == "Day 2 Golden 20 Baseline"
    assert payload["current"]["golden_set_count"] == 20
    assert payload["current"]["dangerous_sql_block_count"] == 38
    assert len(payload["metrics"]) == 4
    assert len(payload["comparisons"]) == 1
