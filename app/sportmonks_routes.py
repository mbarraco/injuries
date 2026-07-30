"""Sportmonks page routes, mounted under /sportmonks by app/main.py.

Mirrors app/af_routes.py's shape: a router with its own prefix, its own page
templates (templates/sportmonks/), sharing only auth, static assets, and the
vendor-neutral base layout/macros. Split out of main.py so the two vendors'
route ownership is symmetric, not just their URLs.

`/api/*` routes are NOT here — they stay in main.py, unprefixed, exactly as
they were. That's the one deliberate exception: AGENTS.md documents external
callers depending on /api/injuries specifically, and this design extends that
same caution to the whole /api/* family rather than moving any of it.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import db, matrix, queries
from app.auth import verify_auth

HERE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

router = APIRouter(prefix="/sportmonks")


def _connection():
    return db.connect()


def _category_or_none(value):
    """"all" (the UI's plain-form choice for "no filter") becomes None."""
    return None if value in (None, "", "all") else value


@router.get("/search", response_class=HTMLResponse)
def page_search(request: Request, q: str = "", _: str = Depends(verify_auth)):
    """Backs the header search box AND works as a real page.

    htmx marks its own requests with the HX-Request header, so that header is
    what distinguishes the two callers: htmx gets the bare results fragment it
    already swaps in, while a plain form submit (no JavaScript) or a shared
    /sportmonks/search?q= link gets a full page with the same results. Without
    this split, the search box only worked with JavaScript enabled.
    """
    with _connection() as connection:
        results = queries.search(connection, q)
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "partials/search_results.html",
                                          {"results": results, "vendor": "sportmonks"})
    return templates.TemplateResponse(request, "sportmonks/search.html",
                                      {"active": "sportmonks-search", "results": results, "query": q,
                                       "vendor": "sportmonks"})


@router.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request, _: str = Depends(verify_auth)):
    """The landing page: a summary of every view, each panel linking into it.
    Coverage kept this slot as a POC; it now lives at /sportmonks/coverage."""
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/dashboard.html",
                                          {"active": "sportmonks-dashboard", **queries.dashboard(connection)})


@router.get("/coverage", response_class=HTMLResponse)
def page_coverage(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/coverage.html", {"active": "sportmonks-coverage", "overview": queries.overview(connection), "quality": queries.quality_metrics(connection), "coverage": queries.coverage_totals(connection), "ramp": queries.coverage_ramp(connection)})


@router.get("/analytics", response_class=HTMLResponse)
def page_analytics(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/analytics.html", {"active": "sportmonks-analytics", "by_position": queries.by_position(connection), "by_age_band": queries.by_age_band(connection), "by_type": queries.by_type(connection), "by_nationality": queries.by_nationality(connection), "by_league": queries.by_league(connection), "by_month": queries.by_month(connection)})


@router.get("/absences", response_class=HTMLResponse)
def page_absences(request: Request, category: str = "injury", country: str | None = None, position: str | None = None,
                  type_name: str | None = None, ongoing_only: bool = False, sort: str = "start_date",
                  direction: str = "desc", page: int = 1, _: str = Depends(verify_auth)):
    with _connection() as connection:
        result = queries.injury_list(connection, category=_category_or_none(category), country=country,
                                     position=position, type_name=type_name, ongoing_only=ongoing_only,
                                     sort=sort, direction=direction, page=page)
        options = queries.filter_options(connection)
    return templates.TemplateResponse(request, "sportmonks/absences.html", {
        "active": "sportmonks-absences", "result": result, "options": options,
        "filters": {"category": category, "country": country, "position": position, "type_name": type_name,
                    "ongoing_only": ongoing_only, "sort": sort, "direction": direction}})


@router.get("/players", response_class=HTMLResponse)
def page_players(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/players.html", {"active": "sportmonks-players", **queries.players_index(connection)})


@router.get("/player/{player_id}", response_class=HTMLResponse)
def page_player(request: Request, player_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        timeline = queries.player_timeline(connection, player_id)
    name = timeline["player"]["name"] if timeline.get("player") else "Unknown player"
    return templates.TemplateResponse(request, "sportmonks/player.html", {
        "active": "sportmonks-players",
        "breadcrumbs": [{"href": "/sportmonks/", "label": "Home"},
                        {"href": "/sportmonks/players", "label": "Players"},
                        {"label": name}],
        **timeline})


@router.get("/leagues", response_class=HTMLResponse)
def page_leagues(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/leagues.html", {"active": "sportmonks-leagues", "leagues": queries.leagues_index(connection)})


@router.get("/league/{league_id}", response_class=HTMLResponse)
def page_league(request: Request, league_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = queries.league_detail(connection, league_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="League not found")
    return templates.TemplateResponse(request, "sportmonks/league.html", {"active": "sportmonks-leagues", **detail})


@router.get("/teams", response_class=HTMLResponse)
def page_teams(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/teams.html", {"active": "sportmonks-teams", "teams": queries.teams_index(connection)})


@router.get("/team/{team_id}", response_class=HTMLResponse)
def page_team(request: Request, team_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = queries.team_detail(connection, team_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return templates.TemplateResponse(request, "sportmonks/team.html", {"active": "sportmonks-teams", **detail})


@router.get("/seasons", response_class=HTMLResponse)
def page_seasons(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/seasons.html", {"active": "sportmonks-seasons", "seasons": queries.seasons_index(connection)})


@router.get("/season/{season_id}", response_class=HTMLResponse)
def page_season(request: Request, season_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = queries.season_detail(connection, season_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Season not found")
    return templates.TemplateResponse(request, "sportmonks/season.html", {"active": "sportmonks-seasons", **detail})


@router.get("/types", response_class=HTMLResponse)
def page_types(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/types.html", {"active": "sportmonks-types", "types": queries.types_index(connection)})


@router.get("/type/{type_id}", response_class=HTMLResponse)
def page_type(request: Request, type_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = queries.type_detail(connection, type_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Injury type not found")
    return templates.TemplateResponse(request, "sportmonks/type.html", {"active": "sportmonks-types", **detail})


@router.get("/transfers", response_class=HTMLResponse)
def page_transfers(request: Request, page: int = 1, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "sportmonks/transfers.html", {
            "active": "sportmonks-transfers", **queries.transfers_index(connection, page=page)})


@router.get("/admin", response_class=HTMLResponse)
def page_admin(request: Request, _: str = Depends(verify_auth)):
    return templates.TemplateResponse(request, "sportmonks/admin/index.html",
                                      {"active": "sportmonks-admin", "measures": matrix.MEASURES})


@router.get("/admin/matrix/{measure}", response_class=HTMLResponse)
def page_matrix(request: Request, measure: str, _: str = Depends(verify_auth)):
    if measure not in matrix.MEASURES:
        raise HTTPException(status_code=404, detail="Unknown measure")
    with _connection() as connection:
        data = matrix.build(connection, measure, scope="league")
    return templates.TemplateResponse(request, "sportmonks/admin/matrix.html", {
        "active": "sportmonks-admin", "data": data, "measure_label": matrix.MEASURES[measure].label,
        "drill_kind": "league" if matrix.MEASURES[measure].supports("club") else None,
        "breadcrumbs": [{"href": "/sportmonks/admin", "label": "Admin"}, {"label": matrix.MEASURES[measure].label}],
    })


@router.get("/admin/matrix/{measure}/league/{league_id}", response_class=HTMLResponse)
def page_matrix_league(request: Request, measure: str, league_id: int, _: str = Depends(verify_auth)):
    if measure not in matrix.MEASURES or not matrix.MEASURES[measure].supports("club"):
        raise HTTPException(status_code=404, detail="Unknown measure or scope")
    with _connection() as connection:
        league = connection.execute("SELECT id, name FROM league WHERE id = ?", (league_id,)).fetchone()
        if league is None:
            raise HTTPException(status_code=404, detail="League not found")
        data = matrix.build(connection, measure, scope="club", scope_id=league_id)
    return templates.TemplateResponse(request, "sportmonks/admin/matrix.html", {
        "active": "sportmonks-admin", "data": data, "measure_label": matrix.MEASURES[measure].label, "drill_kind": "team",
        "breadcrumbs": [{"href": "/sportmonks/admin", "label": "Admin"},
                        {"href": f"/sportmonks/admin/matrix/{measure}", "label": matrix.MEASURES[measure].label},
                        {"label": league["name"]}],
    })


@router.get("/admin/matrix/{measure}/team/{team_id}", response_class=HTMLResponse)
def page_matrix_team(request: Request, measure: str, team_id: int, _: str = Depends(verify_auth)):
    if measure not in matrix.MEASURES or not matrix.MEASURES[measure].supports("player"):
        raise HTTPException(status_code=404, detail="Unknown measure or scope")
    with _connection() as connection:
        team = connection.execute("SELECT id, name FROM team WHERE id = ?", (team_id,)).fetchone()
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        data = matrix.build(connection, measure, scope="player", scope_id=team_id)
    return templates.TemplateResponse(request, "sportmonks/admin/matrix.html", {
        "active": "sportmonks-admin", "data": data, "measure_label": matrix.MEASURES[measure].label, "drill_kind": None,
        "cell_detail": matrix.supports_cell_detail(measure),
        "breadcrumbs": [{"href": "/sportmonks/admin", "label": "Admin"},
                        {"href": f"/sportmonks/admin/matrix/{measure}", "label": matrix.MEASURES[measure].label},
                        {"label": team["name"]}],
    })


@router.get("/admin/matrix/{measure}/player/{player_id}/detail", response_class=HTMLResponse)
def page_matrix_cell_detail(request: Request, measure: str, player_id: int, season: str,
                            _: str = Depends(verify_auth)):
    if not matrix.supports_cell_detail(measure):
        raise HTTPException(status_code=404, detail="No cell-level detail for this measure")
    with _connection() as connection:
        player = connection.execute("SELECT id, name FROM player WHERE id = ?", (player_id,)).fetchone()
        if player is None:
            raise HTTPException(status_code=404, detail="Player not found")
        records = matrix.cell_detail(connection, measure, player_id, season)
    return templates.TemplateResponse(request, "sportmonks/admin/cell_detail.html", {
        "active": "sportmonks-admin", "measure": measure, "measure_label": matrix.MEASURES[measure].label,
        "player": dict(player), "season": season, "records": records,
        "breadcrumbs": [{"href": "/sportmonks/admin", "label": "Admin"},
                        {"href": f"/sportmonks/admin/matrix/{measure}", "label": matrix.MEASURES[measure].label},
                        {"label": player["name"]}, {"label": season}],
    })
