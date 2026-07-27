import base64

import pytest
from fastapi.testclient import TestClient

from app import etl

# Every route is behind HTTP Basic auth (app/main.py verify_auth). Send the
# same credentials on every test request so we exercise the routes, not the
# 401 path.
_AUTH_HEADER = "Basic " + base64.b64encode(b"fernando:1nd3p3nd13nt3").decode()


@pytest.fixture
def client(tmp_path, raw_cache_dir, reference_db, monkeypatch):
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output)
    monkeypatch.setattr("app.db.DB_PATH", str(output))
    from app.main import app
    return TestClient(app, headers={"Authorization": _AUTH_HEADER})


def test_api_overview(client):
    assert client.get("/api/overview").json()["injuries"] == 2


def test_api_injuries_filters_ongoing(client):
    response = client.get("/api/injuries", params={"ongoing_only": True})
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize("path, content", [
    ("/", "Coverage &amp; Data Quality"),
    ("/analytics", "Injuries by position"),
    ("/injuries", "Injury Records"),
    ("/player/5001", "A. Player"),
])
def test_pages_render(client, path, content):
    response = client.get(path)
    assert response.status_code == 200
    assert content in response.text
