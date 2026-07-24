import pytest
from fastapi.testclient import TestClient

from app import etl


@pytest.fixture
def client(tmp_path, raw_cache_dir, reference_db, monkeypatch):
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output)
    monkeypatch.setattr("app.db.DB_PATH", str(output))
    from app.main import app
    return TestClient(app)


def test_api_overview(client):
    assert client.get("/api/overview").json()["injuries"] == 2


def test_api_injuries_filters_ongoing(client):
    response = client.get("/api/injuries", params={"ongoing_only": True})
    assert response.status_code == 200
    assert response.json()["total"] == 1
