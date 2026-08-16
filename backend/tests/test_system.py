def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_version_and_openapi(client):
    version = client.get("/api/v1/version")
    assert version.status_code == 200
    assert version.json()["name"] == "ChatBI V2"
    assert client.get("/openapi.json").status_code == 200
