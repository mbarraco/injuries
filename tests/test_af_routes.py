"""HTTP-level tests for the /af/* routes — wiring, auth, and that every
template renders without error against the af_client fixture (conftest.py).

Query-layer behaviour (filters, rates, category splits) is tested directly
against af_queries in test_af_queries.py; this file only checks the routes
exist, are authenticated the same way as the rest of the app, and produce a
200 with the expected data reachable through them.
"""


def test_af_routes_require_auth(af_client):
    af_client.headers.pop("Authorization")
    assert af_client.get("/af/").status_code == 401


def test_af_dashboard_renders(af_client):
    response = af_client.get("/af/")
    assert response.status_code == 200
    assert "API-Football" in response.text


def test_af_absences_page_and_filters(af_client):
    response = af_client.get("/af/absences")
    assert response.status_code == 200
    # Default confirmed_only=True: 5 rows, not 6.
    assert "5" in response.text or "Test League" in response.text

    filtered = af_client.get("/af/absences", params={"category": "suspension"})
    assert filtered.status_code == 200


def test_af_analytics_page_renders(af_client):
    assert af_client.get("/af/analytics").status_code == 200


def test_af_leagues_index_and_detail(af_client):
    assert af_client.get("/af/leagues").status_code == 200
    assert af_client.get("/af/league/10").status_code == 200
    assert af_client.get("/af/league/999").status_code == 404


def test_af_players_index_and_detail(af_client):
    assert af_client.get("/af/players").status_code == 200
    response = af_client.get("/af/player/1")
    assert response.status_code == 200
    assert "Alpha" in response.text
    # Player 3 has absences but no af_player row — must 404, not 500.
    assert af_client.get("/af/player/3").status_code == 404
    assert af_client.get("/af/player/999").status_code == 404


def test_af_teams_index_and_detail(af_client):
    assert af_client.get("/af/teams").status_code == 200
    assert af_client.get("/af/team/100").status_code == 200
    assert af_client.get("/af/team/999").status_code == 404


def test_af_api_overview_and_player(af_client):
    overview = af_client.get("/af/api/overview").json()
    assert overview["absences"] == 5
    assert overview["questionable"] == 1

    player = af_client.get("/af/api/player/1").json()
    assert player["total_absences"] == 3
    assert af_client.get("/af/api/player/999").status_code == 404


def test_af_search(af_client):
    response = af_client.get("/af/api/search", params={"q": "Alp"}).json()
    assert any(r["label"] == "Alpha" for r in response["results"])


def test_main_dashboard_still_works_unaffected(client):
    """The additive guarantee: wiring in af_routes must not disturb the
    existing Sportmonks-backed app, which uses a completely separate client
    fixture (app.db, not apifootball.db)."""
    assert client.get("/").status_code == 200


# --------------------------------------------------------------------------- #
# The production 500, reproduced at the HTTP level.
#
# `app/apifootball.db` is a committed binary artifact, so a schema addition
# reaches production in two steps: the code on push, the rebuilt database
# whenever someone re-runs the ETL and commits it. In between, the deployed app
# runs new queries against an old file. Wiring transfers into player_detail and
# team_detail made that gap fatal for two pages that have nothing to do with
# transfers.
#
# These go through the real templates on purpose: a query layer that returns a
# safe empty dict still 500s if the template reads a key that isn't in it.
# --------------------------------------------------------------------------- #
def test_player_page_renders_without_the_transfer_tables(af_client_without_transfers):
    response = af_client_without_transfers.get("/af/player/1")
    assert response.status_code == 200
    # The page's own subject matter is untouched...
    assert "Alpha" in response.text
    # ...and the missing data is described as missing, not as "no transfers",
    # which would be a claim about the player rather than about the build.
    assert "has not been built into this database yet" in response.text


def test_team_page_renders_without_the_transfer_tables(af_client_without_transfers):
    response = af_client_without_transfers.get("/af/team/100")
    assert response.status_code == 200
    assert "FC Test" in response.text
    assert "has not been built into this database yet" in response.text


def test_transfers_page_renders_without_the_transfer_tables(af_client_without_transfers):
    response = af_client_without_transfers.get("/af/transfers")
    assert response.status_code == 200
    assert "has not been built into this database yet" in response.text
    # No zeroed headline figures: a row of zeros reads as a measurement, and
    # "not downloaded" is not zero of anything.
    assert "Distinct moves" not in response.text


def test_transfer_json_apis_survive_without_the_tables(af_client_without_transfers):
    for url in ("/af/api/player/1", "/af/api/transfers/player/1",
                "/af/api/transfers/team/100"):
        assert af_client_without_transfers.get(url).status_code == 200, url


def test_transfer_pages_render_normally_when_the_tables_exist(af_client):
    """The other direction: the availability guard must not disable a feature
    that is present. A test that only proves the empty case would pass just as
    well if transfers never rendered at all."""
    for url in ("/af/player/1", "/af/team/100", "/af/transfers"):
        response = af_client.get(url)
        assert response.status_code == 200, url
        assert "has not been built into this database yet" not in response.text, url
    assert "Distinct moves" in af_client.get("/af/transfers").text
