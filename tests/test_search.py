from app import queries


def test_search_matches_players_by_prefix(connection):
    assert any(r["kind"] == "player" for r in queries.search(connection, "A. Pl"))


def test_search_is_case_insensitive(connection):
    assert queries.search(connection, "a. pl") == queries.search(connection, "A. Pl")


def test_short_queries_return_nothing(connection):
    """One-character queries would match thousands of rows and are never useful."""
    assert queries.search(connection, "a") == []


def test_search_matches_teams(connection):
    assert any(r["kind"] == "team" for r in queries.search(connection, "FC"))


def test_search_matches_leagues(connection):
    assert any(r["kind"] == "league" for r in queries.search(connection, "Test Le"))


def test_search_results_link_to_their_entity(connection):
    """Every result must carry an id, so entity_link can build a real href
    rather than the unresolved-entity fallback."""
    for row in queries.search(connection, "A. Pl"):
        assert row["id"] is not None


def test_api_search_returns_json(client):
    response = client.get("/api/search", params={"q": "A. Pl"})
    assert response.status_code == 200
    body = response.json()
    assert any(r["kind"] == "player" for r in body["results"])


def test_search_fragment_renders_links(client):
    """/search is the htmx endpoint: an HTML fragment, not JSON, containing a
    real entity_link href so a result can be clicked straight through."""
    response = client.get("/search", params={"q": "A. Pl"})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'href="/player/5001"' in response.text


def test_search_fragment_empty_for_short_query(client):
    response = client.get("/search", params={"q": "a"})
    assert response.status_code == 200
    assert response.text.strip() == "" or "no results" in response.text.lower()
