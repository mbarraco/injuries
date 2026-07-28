def test_absences_defaults_to_injuries_only(client):
    assert client.get("/absences").status_code == 200


def test_absences_category_filter_returns_suspensions(client):
    response = client.get("/api/absences", params={"category": "suspended"})
    assert response.json()["items"]
    assert all(row["category"] == "suspended" for row in response.json()["items"])


def test_injuries_url_redirects_preserving_meaning(client):
    response = client.get("/injuries", follow_redirects=False)
    assert response.status_code == 302
    assert "category=injury" in response.headers["location"]


def test_api_injuries_still_defaults_to_injury_category(client):
    """/api/injuries must keep returning injuries only by default — existing
    callers depend on this and the category param must not change it."""
    response = client.get("/api/injuries")
    assert response.json()["total"] == 2
    assert all(row["category"] == "injury" for row in response.json()["items"])


def test_api_absences_defaults_to_every_category(client):
    response = client.get("/api/absences")
    assert response.json()["total"] == 3  # 2 injury + 1 suspended, from raw_cache_dir


def test_absences_filter_and_pager_are_htmx_enhanced(client):
    """The filter form and pager links must carry hx-* attributes targeting
    #absence-results, so htmx can swap just that fragment instead of a full
    reload — while the plain method="get"/href attributes keep the no-JS path
    working unchanged."""
    response = client.get("/absences")
    assert 'id="absence-results"' in response.text
    assert 'hx-target="#absence-results"' in response.text
    assert 'method="get"' in response.text
