def test_absences_defaults_to_injuries_only(client):
    assert client.get("/sportmonks/absences").status_code == 200


def test_absences_category_filter_returns_suspensions(client):
    response = client.get("/api/absences", params={"category": "suspended"})
    assert response.json()["items"]
    assert all(row["category"] == "suspended" for row in response.json()["items"])


def test_injuries_url_no_longer_exists(client):
    """The /injuries -> /absences redirect is removed as part of the clean
    cutover to /sportmonks/*: no legacy page redirects are kept. /api/injuries
    is unaffected -- see test_api_injuries_still_defaults_to_injury_category."""
    assert client.get("/injuries").status_code == 404


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
    response = client.get("/sportmonks/absences")
    assert 'id="absence-results"' in response.text
    assert 'hx-target="#absence-results"' in response.text
    assert 'method="get"' in response.text


def test_paging_preserves_the_active_filter(client):
    """Pager links must EXTEND the query string, not replace it.

    A bare href="?page=2" drops every other param, so the route's defaults take
    over: paging through 'suspended' silently returned injuries while the
    dropdown still read 'Suspended'. Uses page=2 so the Prev link renders — the
    fixture has too few rows to produce a Next link.
    """
    import re

    response = client.get("/sportmonks/absences", params={"category": "suspended", "page": 2})
    pager = re.search(r'<div class="pager">.*?href="([^"]+)"', response.text, re.S)
    assert pager, "expected a pager link on page 2"

    href = pager.group(1)
    assert "category=suspended" in href, f"filter dropped from pager link: {href}"
    assert "page=1" in href
