def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_version_and_openapi(client):
    version = client.get("/api/v1/version")
    assert version.status_code == 200
    assert version.json()["name"] == "ChatBI V2"
    assert version.json()["version"] == "1.4.0"
    assert client.get("/openapi.json").status_code == 200


def test_model_provider_status_never_exposes_credentials(client):
    response = client.get("/api/v1/model-providers")
    assert response.status_code == 200
    body = response.json()
    assert body["secrets_exposed"] is False
    assert {item["id"] for item in body["items"]} >= {"kimi", "mimo", "deepseek", "deterministic"}
    assert all("api_key" not in item for item in body["items"])
