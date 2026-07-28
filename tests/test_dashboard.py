def test_dashboard_links_into_every_view(client):
    """The dashboard is the entry into the navigation graph, so every view has
    to be reachable from it without typing a URL."""
    response = client.get("/")

    for href in ("/absences", "/players", "/teams", "/leagues", "/seasons",
                 "/types", "/analytics", "/coverage"):
        assert f'href="{href}"' in response.text, f"dashboard does not link to {href}"


def test_dashboard_warns_about_coverage(client):
    """Coverage ramps over time, which makes cross-year comparison invalid.
    That is the dataset's biggest trap, so a reader meets it on the way in
    rather than only if they visit /coverage."""
    text = client.get("/").text.lower()

    assert "coverage" in text
    assert "/coverage" in text


def test_dashboard_shows_headline_totals(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Absences" in response.text
    assert "Injuries" in response.text


def test_dashboard_summarises_each_view_with_real_rows(client):
    """Summary cards show actual top rows, not just headings — each row links
    to the entity it names."""
    response = client.get("/")

    assert 'href="/player/5001"' in response.text
    assert 'href="/team/100"' in response.text
    assert 'href="/league/10"' in response.text


def test_coverage_page_moved_off_the_dashboard(client):
    """Good POC landing page, poor product homepage: it keeps its content at
    its own URL."""
    response = client.get("/coverage")

    assert response.status_code == 200
    assert "Coverage &amp; Data Quality" in response.text


def test_players_index_lists_and_links_players(client):
    response = client.get("/players")

    assert response.status_code == 200
    assert 'href="/player/5001"' in response.text


def test_players_index_reports_the_real_total_when_capped(connection, monkeypatch):
    """13k players is not a page. The cap is fine; presenting the cap as the
    population is not."""
    from app import queries

    monkeypatch.setattr(queries, "PLAYER_INDEX_LIMIT", 1)
    result = queries.players_index(connection)

    assert len(result["players"]) == 1
    assert result["total"] == 2  # 5001 and 5003 are the fixture's players
