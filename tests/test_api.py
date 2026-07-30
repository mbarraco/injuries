import pytest


def test_api_overview(client):
    assert client.get("/api/overview").json()["injuries"] == 2


def test_api_injuries_filters_ongoing(client):
    response = client.get("/api/injuries", params={"ongoing_only": True})
    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize("path, content", [
    # Coverage moved off "/sportmonks/" — good POC landing page, poor product
    # homepage. "/" itself is now the neutral two-vendor landing page, not this
    # dashboard — see test_home.py.
    ("/sportmonks/", "Dashboard"),
    ("/sportmonks/coverage", "Coverage &amp; Data Quality"),
    ("/sportmonks/analytics", "Injuries by position"),
    ("/sportmonks/absences", "Absences"),
    ("/sportmonks/player/5001", "A. Player"),
])
def test_pages_render(client, path, content):
    response = client.get(path)
    assert response.status_code == 200
    assert content in response.text
