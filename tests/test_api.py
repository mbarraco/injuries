import base64

import pytest
from fastapi.testclient import TestClient

from app import auth, etl

# Every route is behind HTTP Basic auth (app/main.py verify_auth). Credentials
# come from the environment, so the tests set their own rather than depending
# on whatever the developer has in .env.
_USER, _PASSWORD = "tester", "testpass"
_AUTH_HEADER = "Basic " + base64.b64encode(f"{_USER}:{_PASSWORD}".encode()).decode()


@pytest.fixture
def client(tmp_path, raw_cache_dir, reference_db, monkeypatch):
    monkeypatch.setenv(auth.USER_VAR, _USER)
    monkeypatch.setenv(auth.PASSWORD_VAR, _PASSWORD)
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
