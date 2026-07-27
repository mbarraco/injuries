def test_league_page_lists_teams_and_links_them(client):
    response = client.get("/league/10")
    assert response.status_code == 200
    assert "Test League" in response.text
    assert 'href="/team/100"' in response.text


def test_leagues_index_lists_all_leagues(client):
    response = client.get("/leagues")
    assert 'href="/league/10"' in response.text


def test_unknown_league_is_404(client):
    assert client.get("/league/999999").status_code == 404
