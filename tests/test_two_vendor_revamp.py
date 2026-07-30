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
