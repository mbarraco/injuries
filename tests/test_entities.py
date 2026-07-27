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


def test_team_page_links_players_and_league(client):
    response = client.get("/team/100")
    assert response.status_code == 200
    assert 'href="/player/5001"' in response.text
    assert 'href="/league/10"' in response.text


def test_teams_index_lists_all_teams(client):
    response = client.get("/teams")
    assert 'href="/team/100"' in response.text


def test_unknown_team_is_404(client):
    assert client.get("/team/999999").status_code == 404


def test_type_page_shows_name_and_links_players(client):
    response = client.get("/type/500")
    assert response.status_code == 200
    assert "Knock" in response.text
    assert 'href="/player/' in response.text


def test_types_index_lists_all_types(client):
    response = client.get("/types")
    assert 'href="/type/500"' in response.text


def test_unknown_type_is_404(client):
    assert client.get("/type/999999").status_code == 404


def test_injuries_table_links_team_league_and_type(client):
    response = client.get("/injuries")
    assert 'href="/team/100"' in response.text
    assert 'href="/league/10"' in response.text
    assert 'href="/type/500"' in response.text


def test_player_page_links_team_league_and_type(client):
    response = client.get("/player/5001")
    assert 'href="/team/100"' in response.text
    assert 'href="/league/10"' in response.text
    assert 'href="/type/500"' in response.text
