import pytest

from app import queries


def test_minutes_are_summed_across_a_mid_season_move(rates_connection):
    """The grain is (player, season), with minutes summed across clubs.

    player_season is keyed (player, season, team), so player 5003 — who moved
    mid-season — has two rows for season 77 (300 + 400 minutes). Joining
    absence straight onto that table multiplies his single injury across both
    rows and divides it by one club's minutes: two rows at 3.33 per 1000
    instead of one at 1.43. Nothing raises; the number is just wrong. This
    pins the intended answer.
    """
    result = queries.player_rates(rates_connection, season_id=77)
    matching = [row for row in result["players"] if row["id"] == 5003]

    assert len(matching) == 1, "a mid-season move must not produce two ranking rows"
    assert matching[0]["minutes_played"] == 700
    assert matching[0]["injuries"] == 1
    assert matching[0]["rate_per_1000"] == 1.43  # 1 ÷ (700 ÷ 1000)


def test_excludes_players_below_the_minutes_floor(rates_connection):
    """A player with 90 minutes and one injury scores 11.11 per 1000, twenty
    times a regular starter, purely as an artefact of a tiny denominator."""
    result = queries.player_rates(rates_connection, season_id=77)

    assert all(row["minutes_played"] >= queries.MINUTES_FLOOR for row in result["players"])
    assert 5001 not in {row["id"] for row in result["players"]}


def test_reports_the_excluded_players_instead_of_hiding_them(rates_connection):
    """A silent exclusion is how a reader draws a wrong conclusion: the page
    has to be able to say how many players the floor removed."""
    result = queries.player_rates(rates_connection, season_id=77)

    assert result["below_floor"] == 1
    assert result["minutes_floor"] == 450


def test_reports_minutes_alongside_every_rate(rates_connection):
    """The basis must travel with the number so a reader can judge it."""
    for row in queries.player_rates(rates_connection, season_id=77)["players"]:
        assert row["minutes_played"] is not None
        assert row["rate_per_1000"] is not None


def test_team_rate_uses_minutes_and_injuries_at_that_team(connection):
    """A team page asks "how did this player fare HERE", so both sides are
    scoped to the club — (player, season, team) grain, unlike the season
    page's whole-season figure."""
    result = queries.team_rates(connection, 100)
    row = next(item for item in result["players"] if item["id"] == 5001)

    assert row["minutes_played"] == 944
    assert row["injuries"] == 1
    assert row["rate_per_1000"] == 1.06  # 1 ÷ (944 ÷ 1000)


def test_season_page_shows_rates_with_minutes_and_the_floor(client):
    response = client.get("/season/77")

    assert "per 1000 minutes" in response.text
    assert "944" in response.text  # the minutes basis, beside the rate
    assert "450" in response.text  # the floor, named on the page


def test_team_page_shows_rates_with_the_floor(client):
    response = client.get("/team/100")

    assert "per 1000 minutes" in response.text
    assert "450" in response.text


def test_rates_are_scoped_to_one_season(rates_connection):
    """Cross-season ranking would measure the vendor's coverage ramp, not
    injury risk, so a season is required rather than optional."""
    with pytest.raises(TypeError):
        queries.player_rates(rates_connection)


def test_empty_rates_explain_a_young_season_not_missing_data(rates_client):
    """Players with minutes but none past the floor is "not yet", not "no data".

    Only 12 of 53 current seasons currently have anyone above 450 minutes
    because 2026/2027 has barely started, so this is the state most team pages
    are in — it must not read as a broken feature.
    """
    body = rates_client.get("/team/100").text
    assert "Early in a season that is expected" in body
    assert "recorded minutes" in body


def test_empty_rates_say_so_plainly_when_there_are_no_minutes_at_all(client):
    """The other branch: nothing recorded, so there is nothing to wait for."""
    body = client.get("/team/200").text
    assert "No minutes are recorded" in body
    assert "Early in a season" not in body
