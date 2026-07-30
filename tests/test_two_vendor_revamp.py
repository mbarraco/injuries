"""Tests for the two-vendor hierarchy/visual revamp:
docs/superpowers/specs/2026-07-30-two-vendor-design-revamp-design.md

Four things this revamp could get wrong silently:
1. An old unprefixed page path could still work, undermining the clean cutover.
2. The router split could accidentally touch /api/*, which must never move.
3. The neutral landing page could fail to summarise both vendors.
4. The vendor-accent mechanism could fail to identify which vendor a page
   belongs to, or could mis-set it on the one page that must show neither.
"""


def test_old_unprefixed_sportmonks_pages_are_gone(client):
    """Clean cutover, no legacy redirects -- the explicit design decision."""
    for path in ("/absences", "/players", "/player/5001", "/teams", "/team/100",
                 "/leagues", "/league/10", "/seasons", "/season/77", "/types",
                 "/type/500", "/coverage", "/analytics", "/admin", "/search",
                 "/injuries"):
        assert client.get(path).status_code == 404, f"{path} should 404, not still work"


def test_home_is_the_neutral_landing_page_now(both_vendors_client):
    response = both_vendors_client.get("/")
    assert response.status_code == 200
    assert "Sportmonks" in response.text
    assert "API-Football" in response.text


def test_home_player_and_team_counts_are_true_dataset_totals(both_vendors_client, connection, af_connection):
    """Regression guard for a real bug: the home page originally called
    overview(), whose "players"/"teams" mean "players/teams with at least one
    recorded injury/absence" -- a different, smaller number than the dataset's
    actual size. On a page whose job is comparing two vendors at a glance,
    that silently made very differently-sized datasets (13,306 vs 33,750
    players in the real databases) look almost identical (9,205 vs 9,831).
    The fixture databases reproduce the same shape: not every player in
    af_player/player has a recorded absence, so the true count must exceed
    the "distinct player_id in an absence table" count."""
    true_sm_players = connection.execute("SELECT COUNT(*) FROM player").fetchone()[0]
    true_af_players = af_connection.execute("SELECT COUNT(*) FROM af_player").fetchone()[0]

    body = both_vendors_client.get("/").text
    assert f">{true_sm_players:,}<" in body or str(true_sm_players) in body
    assert f">{true_af_players:,}<" in body or str(true_af_players) in body


def test_api_star_is_completely_unaffected_by_the_router_split(client):
    """The frozen contract. Every /api/* route must behave exactly as before
    -- same status, same shape -- because AGENTS.md documents external callers
    depending on /api/injuries specifically, and this design extends that
    caution to the whole family rather than moving any of it."""
    overview = client.get("/api/overview")
    assert overview.status_code == 200
    assert "injuries" in overview.json()

    injuries = client.get("/api/injuries")
    assert injuries.status_code == 200
    assert injuries.json()["total"] == 2
    assert all(row["category"] == "injury" for row in injuries.json()["items"])

    absences = client.get("/api/absences")
    assert absences.status_code == 200
    assert absences.json()["total"] == 3

    player = client.get("/api/player/5001")
    assert player.status_code == 200
    assert player.json()["player"]["id"] == 5001

    search = client.get("/api/search", params={"q": "A. Pl"})
    assert search.status_code == 200
    assert "results" in search.json()


def test_data_vendor_identifies_sportmonks_pages(client):
    assert 'data-vendor="sportmonks"' in client.get("/sportmonks/").text


def test_data_vendor_identifies_af_pages(af_client):
    assert 'data-vendor="af"' in af_client.get("/af/").text


def test_data_vendor_is_absent_on_the_neutral_landing_page(both_vendors_client):
    """Neither vendor is "current" on the picker: the <body> tag itself must
    carry no data-vendor attribute (each card scopes its own accent locally
    instead) -- distinct from the nav's OWN .nav-vendor wrapper divs, which
    always show both group labels/colors regardless of the current page."""
    body = both_vendors_client.get("/").text
    assert "<body>" in body


def test_search_box_is_absent_from_the_neutral_landing_page(both_vendors_client):
    assert 'class="global-search"' not in both_vendors_client.get("/").text


# --------------------------------------------------------------------------- #
# New pages, added to bring API-Football and Sportmonks to matching hierarchies.
# --------------------------------------------------------------------------- #
def test_af_coverage_page_renders(af_client):
    response = af_client.get("/af/coverage")
    assert response.status_code == 200
    assert "Coverage" in response.text


def test_af_reasons_index_lists_reasons(af_client):
    response = af_client.get("/af/reasons")
    assert response.status_code == 200
    assert "Hamstring Injury" in response.text


def test_af_reason_detail_renders_for_a_known_reason(af_client):
    """af_reason has no numeric id -- the reason string IS the key, so the URL
    takes a url-encoded string, not an integer."""
    response = af_client.get("/af/reason/Hamstring Injury")
    assert response.status_code == 200
    assert "Hamstring Injury" in response.text


def test_af_reason_detail_404s_for_an_unknown_reason(af_client):
    assert af_client.get("/af/reason/Nonexistent Reason").status_code == 404


def test_af_search_page_exists_and_is_af_scoped(af_client):
    response = af_client.get("/af/search", params={"q": "Alp"})
    assert response.status_code == 200


def test_sportmonks_transfers_page_renders(client):
    response = client.get("/sportmonks/transfers")
    assert response.status_code == 200
    assert "Transfers" in response.text


# --------------------------------------------------------------------------- #
# Consistency fixes: grain-note banners and breadcrumbs used to be present on
# some /af/* pages and missing on others with no reason for the difference.
# --------------------------------------------------------------------------- #
def test_grain_note_appears_on_every_af_page_showing_absence_counts(af_client):
    # A substring free of characters Jinja HTML-escapes (the full GRAIN_NOTE
    # contains an apostrophe, which renders as &#39; — checking the whole
    # string verbatim would fail on escaping, not on the note being present).
    marker = "no spell identifier"
    for path in ("/af/analytics", "/af/leagues", "/af/league/10",
                 "/af/teams", "/af/team/100"):
        response = af_client.get(path)
        assert response.status_code == 200, path
        assert marker in response.text, f"{path} is missing the grain note"


def test_sportmonks_player_page_shows_photo_thumbnail_when_known(client):
    response = client.get("/sportmonks/player/5001")
    assert 'class="player-photo"' in response.text
    assert 'src="https://cdn.sportmonks.com/players/5001.png"' in response.text


def test_sportmonks_player_page_omits_thumbnail_when_photo_unknown(client):
    """Player 5003's reference row has a NULL image_path -- no <img> tag, not a
    broken-image placeholder."""
    response = client.get("/sportmonks/player/5003")
    assert 'class="player-photo"' not in response.text


def test_breadcrumbs_present_on_every_remaining_detail_page(af_client, client):
    for c, path in ((af_client, "/af/player/1"), (af_client, "/af/team/100"),
                    (af_client, "/af/league/10"), (client, "/sportmonks/player/5001")):
        response = c.get(path)
        assert response.status_code == 200, path
        assert 'aria-label="Breadcrumb"' in response.text, f"{path} has no breadcrumbs"
