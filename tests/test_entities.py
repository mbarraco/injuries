def test_league_page_lists_teams_and_links_them(client):
    response = client.get("/sportmonks/league/10")
    assert response.status_code == 200
    assert "Test League" in response.text
    assert 'href="/sportmonks/team/100"' in response.text


def test_leagues_index_lists_all_leagues(client):
    response = client.get("/sportmonks/leagues")
    assert 'href="/sportmonks/league/10"' in response.text


def test_unknown_league_is_404(client):
    assert client.get("/sportmonks/league/999999").status_code == 404


def test_team_page_links_players_and_league(client):
    response = client.get("/sportmonks/team/100")
    assert response.status_code == 200
    assert 'href="/sportmonks/player/5001"' in response.text
    assert 'href="/sportmonks/league/10"' in response.text


def test_teams_index_lists_all_teams(client):
    response = client.get("/sportmonks/teams")
    assert 'href="/sportmonks/team/100"' in response.text


def test_unknown_team_is_404(client):
    assert client.get("/sportmonks/team/999999").status_code == 404


def test_type_page_shows_name_and_links_players(client):
    response = client.get("/sportmonks/type/500")
    assert response.status_code == 200
    assert "Knock" in response.text
    assert 'href="/sportmonks/player/' in response.text


def test_types_index_lists_all_types(client):
    response = client.get("/sportmonks/types")
    assert 'href="/sportmonks/type/500"' in response.text


def test_unknown_type_is_404(client):
    assert client.get("/sportmonks/type/999999").status_code == 404


def test_injuries_table_links_team_league_and_type(client):
    response = client.get("/sportmonks/absences?category=injury")
    assert 'href="/sportmonks/team/100"' in response.text
    assert 'href="/sportmonks/league/10"' in response.text
    assert 'href="/sportmonks/type/500"' in response.text


def test_player_page_links_team_league_and_type(client):
    response = client.get("/sportmonks/player/5001")
    assert 'href="/sportmonks/team/100"' in response.text
    assert 'href="/sportmonks/league/10"' in response.text
    assert 'href="/sportmonks/type/500"' in response.text


def test_player_page_shows_season_minutes_and_transfer_history(client):
    response = client.get("/sportmonks/player/5001")
    assert 'href="/sportmonks/season/77"' in response.text  # per-season minutes, season linked
    assert "944" in response.text                # the minutes figure itself
    assert 'href="/sportmonks/team/200"' in response.text    # transfer history, from-club linked


def test_capped_lists_report_the_real_total_not_the_page_size(connection, monkeypatch):
    """A capped table must not present its page size as the total.

    Team 88 in the real database holds 290 absences; before this, the heading
    read "Absences (50)" because it counted the returned rows. The fixture team
    has 2 injury-category absences (900, 902), so the cap is lowered to make
    truncation happen.
    """
    from app import queries

    monkeypatch.setattr(queries, "ABSENCE_LIMIT", 1)
    detail = queries.team_detail(connection, 100)

    assert len(detail["absences"]) == 1        # truncated, as asked
    assert detail["absences_total"] == 2       # but the total is still honest


def test_team_absences_default_to_injury_category(connection):
    """Team pages used to list every category while league/type pages already
    filtered to 'injury' — now that the category filter exists, team pages
    match that default explicitly instead of incidentally showing everything."""
    from app import queries

    detail = queries.team_detail(connection, 100)
    assert all(row["category"] == "injury" for row in detail["absences"])


def test_type_page_reports_total_players_affected(connection, monkeypatch):
    from app import queries

    monkeypatch.setattr(queries, "PLAYER_LIMIT", 1)
    detail = queries.type_detail(connection, 500)

    assert len(detail["players"]) == 1
    assert detail["players_total"] == 2        # 5001 and 5003 both had type 500


def test_season_page_links_league(client):
    response = client.get("/sportmonks/season/77")
    assert response.status_code == 200
    assert "Test League" in response.text
    assert 'href="/sportmonks/league/10"' in response.text


def test_seasons_index_lists_all_seasons(client):
    response = client.get("/sportmonks/seasons")
    assert 'href="/sportmonks/season/77"' in response.text


def test_unknown_season_is_404(client):
    assert client.get("/sportmonks/season/999999").status_code == 404


def test_team_squad_uses_current_season(connection):
    """The squad picks players via season.is_current, not MAX(season_id).

    MAX(season_id) silently assumes ids are chronological; is_current is the
    column the schema already populates for exactly this purpose.
    """
    from app import queries

    detail = queries.team_detail(connection, 100)
    squad_ids = {row["id"] for row in detail["squad"]}
    assert 5001 in squad_ids   # season 77, is_current
    assert 5003 not in squad_ids  # season 78, higher id but not current


def test_squad_lists_each_player_once_across_competitions(multi_competition_connection):
    """A club current in its league AND a cup must not list a player twice.

    Before the cups reached the season dimension only one season per club was
    ever current, so an ungrouped query looked correct. Afterwards a real team
    page read "Squad (12)" while showing 9 people.
    """
    from app import queries

    squad = queries.team_detail(multi_competition_connection, 100)["squad"]

    assert len(squad) == 1
    assert squad[0]["id"] == 5001


def test_squad_minutes_sum_across_competitions(multi_competition_connection):
    """944 in the league plus 200 in the cup is 1144 minutes for one player,
    and the row says how many competitions the total spans."""
    from app import queries

    player = queries.team_detail(multi_competition_connection, 100)["squad"][0]

    assert player["minutes_played"] == 1144
    assert player["competitions"] == 2
