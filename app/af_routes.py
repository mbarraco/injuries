"""API-Football routes, mounted under /af by app/main.py.

Additive only: nothing here touches the existing Sportmonks routes, database,
or templates. Shares `auth` (including `verify_auth`), `db` (via
`connect_af`), and the base layout / macros — see
`docs/superpowers/plans/2026-07-29-apifootball-ingestion.md` for why a full
second app was rejected in favour of this.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import af_queries, auth, db
from app.auth import verify_auth

HERE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

router = APIRouter(prefix="/af")


def _connection():
    return db.connect_af()


def _category_or_none(value):
    return None if value in (None, "", "all") else value


# --------------------------------------------------------------------------- #
# JSON API.
# --------------------------------------------------------------------------- #
@router.get("/api/overview")
def api_overview(_: str = Depends(verify_auth)):
    with _connection() as connection:
        return {**af_queries.overview(connection), "quality": af_queries.quality_metrics(connection)}


@router.get("/api/absences")
def api_absences(confirmed_only: bool = True, category: str | None = None,
                 league_id: int | None = None, season: int | None = None,
                 country: str | None = None, sort: str = "fixture_date",
                 direction: str = "desc", page: int = 1, per_page: int = 50,
                 _: str = Depends(verify_auth)):
    with _connection() as connection:
        return af_queries.absence_list(connection, confirmed_only=confirmed_only,
                                       category=_category_or_none(category),
                                       league_id=league_id, season=season,
                                       country=country, sort=sort,
                                       direction=direction, page=page, per_page=per_page)


@router.get("/api/player/{player_id}")
def api_player(player_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = af_queries.player_detail(connection, player_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return detail


@router.get("/api/transfers/player/{player_id}")
def api_player_transfers(player_id: int, _: str = Depends(verify_auth)):
    """A player's career. Deliberately NOT 404 for a player with no af_player
    row: most of these people predate the 2020–2025 window every other table is
    capped to, so their career exists even when their profile doesn't."""
    with _connection() as connection:
        return af_queries.player_transfers(connection, player_id)


@router.get("/api/transfers/team/{team_id}")
def api_team_transfers(team_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return af_queries.team_transfers(connection, team_id)


@router.get("/api/search")
def api_search(q: str = "", _: str = Depends(verify_auth)):
    with _connection() as connection:
        return {"results": af_queries.search(connection, q)}


# --------------------------------------------------------------------------- #
# Pages.
# --------------------------------------------------------------------------- #
@router.get("/search", response_class=HTMLResponse)
def page_search(request: Request, q: str = "", _: str = Depends(verify_auth)):
    """Mirrors sportmonks_routes.page_search exactly, but scoped to
    API-Football's own database and query layer. Searching from an /af/* page
    used to silently query Sportmonks data through the one shared search box —
    this and the vendor-scoped retargeting in base.html are what fix that."""
    with _connection() as connection:
        results = af_queries.search(connection, q)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "partials/search_results.html",
                                          {"results": results, "vendor": "af"})
    return templates.TemplateResponse(request, "af/search.html", {
        "active": "af-search", "results": results, "query": q, "vendor": "af"})


@router.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "af/dashboard.html",
                                          {"active": "af-dashboard", **af_queries.dashboard(connection)})


@router.get("/absences", response_class=HTMLResponse)
def page_absences(request: Request, confirmed_only: bool = True, category: str | None = None,
                  league_id: int | None = None, season: int | None = None,
                  country: str | None = None, sort: str = "fixture_date",
                  direction: str = "desc", page: int = 1, _: str = Depends(verify_auth)):
    with _connection() as connection:
        result = af_queries.absence_list(connection, confirmed_only=confirmed_only,
                                         category=_category_or_none(category),
                                         league_id=league_id, season=season,
                                         country=country, sort=sort,
                                         direction=direction, page=page)
        options = af_queries.filter_options(connection)
    return templates.TemplateResponse(request, "af/absences.html", {
        "active": "af-absences", "result": result, "options": options,
        "filters": {"confirmed_only": confirmed_only, "category": category,
                    "league_id": league_id, "season": season, "country": country,
                    "sort": sort, "direction": direction}})


@router.get("/analytics", response_class=HTMLResponse)
def page_analytics(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "af/analytics.html", {
            "active": "af-analytics",
            "by_position": af_queries.by_position(connection),
            "by_age_band": af_queries.by_age_band(connection),
            "by_reason": af_queries.by_reason(connection),
            "by_league": af_queries.by_league(connection),
            "by_month": af_queries.by_month(connection),
            "grain_note": af_queries.GRAIN_NOTE,
        })


@router.get("/transfers", response_class=HTMLResponse)
def page_transfers(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "af/transfers.html", {
            "active": "af-transfers",
            "overview": af_queries.transfer_overview(connection),
            "categories": af_queries.transfer_categories(connection),
            "by_year": af_queries.transfers_by_year(connection),
        })


@router.get("/coverage", response_class=HTMLResponse)
def page_coverage(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "af/coverage.html", {
            "active": "af-coverage",
            "overview": af_queries.overview(connection),
            "quality": af_queries.quality_metrics(connection),
        })


@router.get("/leagues", response_class=HTMLResponse)
def page_leagues(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "af/leagues.html", {
            "active": "af-leagues", "leagues": af_queries.leagues_index(connection),
            "grain_note": af_queries.GRAIN_NOTE})


@router.get("/league/{league_id}", response_class=HTMLResponse)
def page_league(request: Request, league_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = af_queries.league_detail(connection, league_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="League not found")
    return templates.TemplateResponse(request, "af/league.html", {
        "active": "af-leagues", "grain_note": af_queries.GRAIN_NOTE,
        "breadcrumbs": [{"href": "/", "label": "Home"},
                        {"href": "/af/leagues", "label": "Leagues"},
                        {"label": detail["league"]["name"]}],
        **detail})


@router.get("/reasons", response_class=HTMLResponse)
def page_reasons(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "af/reasons.html",
                                          {"active": "af-reasons", "reasons": af_queries.reasons_index(connection)})


@router.get("/reason/{reason}", response_class=HTMLResponse)
def page_reason(request: Request, reason: str, _: str = Depends(verify_auth)):
    """`reason` is a URL-encoded free-text string, not an integer -- af_reason
    has no numeric id, the reason text itself is the vendor's own key
    (schema_af.sql)."""
    with _connection() as connection:
        detail = af_queries.reason_detail(connection, reason)
    if detail is None:
        raise HTTPException(status_code=404, detail="Reason not found")
    return templates.TemplateResponse(request, "af/reason.html", {"active": "af-reasons", **detail})


@router.get("/players", response_class=HTMLResponse)
def page_players(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "af/players.html",
                                          {"active": "af-players", **af_queries.players_index(connection)})


@router.get("/player/{player_id}", response_class=HTMLResponse)
def page_player(request: Request, player_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = af_queries.player_detail(connection, player_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return templates.TemplateResponse(request, "af/player.html", {
        "active": "af-players",
        "breadcrumbs": [{"href": "/", "label": "Home"},
                        {"href": "/af/players", "label": "Players"},
                        {"label": detail["player"]["name"]}],
        **detail})


@router.get("/teams", response_class=HTMLResponse)
def page_teams(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "af/teams.html", {
            "active": "af-teams", "teams": af_queries.teams_index(connection),
            "grain_note": af_queries.GRAIN_NOTE})


@router.get("/team/{team_id}", response_class=HTMLResponse)
def page_team(request: Request, team_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = af_queries.team_detail(connection, team_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return templates.TemplateResponse(request, "af/team.html", {
        "active": "af-teams", "grain_note": af_queries.GRAIN_NOTE,
        "breadcrumbs": [{"href": "/", "label": "Home"},
                        {"href": "/af/teams", "label": "Teams"},
                        {"label": detail["team"]["name"]}],
        **detail})
