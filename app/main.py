"""Thin FastAPI routes over the testable injury query layer."""
import os

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, db, queries

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Injury Data POC")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

security = HTTPBasic()

async def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
    if not auth.verify(credentials.username, credentials.password):
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def _connection():
    return db.connect()


def _category_or_none(value):
    """"all" (the UI's plain-form choice for "no filter") becomes None."""
    return None if value in (None, "", "all") else value


@app.get("/api/overview")
def api_overview(_: str = Depends(verify_auth)):
    with _connection() as connection:
        return {**queries.overview(connection), "quality": queries.quality_metrics(connection)}


@app.get("/api/coverage")
def api_coverage(_: str = Depends(verify_auth)):
    with _connection() as connection:
        return {"leagues": queries.coverage_by_league(connection)}


@app.get("/api/analytics")
def api_analytics(_: str = Depends(verify_auth)):
    with _connection() as connection:
        return {"by_position": queries.by_position(connection), "by_age_band": queries.by_age_band(connection),
                "by_type": queries.by_type(connection), "by_nationality": queries.by_nationality(connection),
                "by_league": queries.by_league(connection), "by_month": queries.by_month(connection)}


@app.get("/api/injuries")
def api_injuries(category: str = "injury", country: str | None = None, position: str | None = None,
                 type_name: str | None = None, ongoing_only: bool = False, sort: str = "start_date",
                 direction: str = "desc", page: int = 1, per_page: int = 50, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return queries.injury_list(connection, category=_category_or_none(category), country=country,
                                   position=position, type_name=type_name, ongoing_only=ongoing_only, sort=sort,
                                   direction=direction, page=page, per_page=per_page)


@app.get("/api/absences")
def api_absences(category: str | None = None, country: str | None = None, position: str | None = None,
                 type_name: str | None = None, ongoing_only: bool = False, sort: str = "start_date",
                 direction: str = "desc", page: int = 1, per_page: int = 50, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return queries.injury_list(connection, category=_category_or_none(category), country=country,
                                   position=position, type_name=type_name, ongoing_only=ongoing_only, sort=sort,
                                   direction=direction, page=page, per_page=per_page)


@app.get("/api/player/{player_id}")
def api_player(player_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return queries.player_timeline(connection, player_id)


@app.get("/api/search")
def api_search(q: str = "", _: str = Depends(verify_auth)):
    with _connection() as connection:
        return {"results": queries.search(connection, q)}


@app.get("/search", response_class=HTMLResponse)
def page_search(request: Request, q: str = "", _: str = Depends(verify_auth)):
    """The htmx fragment behind the header search box. Not part of the JSON
    API — external callers should use /api/search instead."""
    with _connection() as connection:
        results = queries.search(connection, q)
    return templates.TemplateResponse(request, "partials/search_results.html", {"results": results})


@app.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request, _: str = Depends(verify_auth)):
    """The landing page: a summary of every view, each panel linking into it.
    Coverage kept this slot as a POC; it now lives at /coverage."""
    with _connection() as connection:
        return templates.TemplateResponse(request, "dashboard.html",
                                          {"active": "dashboard", **queries.dashboard(connection)})


@app.get("/coverage", response_class=HTMLResponse)
def page_coverage(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "coverage.html", {"active": "coverage", "overview": queries.overview(connection), "quality": queries.quality_metrics(connection), "coverage": queries.coverage_totals(connection), "ramp": queries.coverage_ramp(connection)})


@app.get("/analytics", response_class=HTMLResponse)
def page_analytics(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "analytics.html", {"active": "analytics", "by_position": queries.by_position(connection), "by_age_band": queries.by_age_band(connection), "by_type": queries.by_type(connection), "by_nationality": queries.by_nationality(connection), "by_league": queries.by_league(connection), "by_month": queries.by_month(connection)})


@app.get("/injuries")
def page_injuries_redirect():
    """Preserved so existing links and bookmarks keep working. 302, not 301:
    a permanent redirect is cached hard by browsers and hard to walk back."""
    return RedirectResponse("/absences?category=injury", status_code=302)


@app.get("/absences", response_class=HTMLResponse)
def page_absences(request: Request, category: str = "injury", country: str | None = None, position: str | None = None,
                  type_name: str | None = None, ongoing_only: bool = False, sort: str = "start_date",
                  direction: str = "desc", page: int = 1, _: str = Depends(verify_auth)):
    with _connection() as connection:
        result = queries.injury_list(connection, category=_category_or_none(category), country=country,
                                     position=position, type_name=type_name, ongoing_only=ongoing_only,
                                     sort=sort, direction=direction, page=page)
        options = queries.filter_options(connection)
    return templates.TemplateResponse(request, "absences.html", {
        "active": "absences", "result": result, "options": options,
        "filters": {"category": category, "country": country, "position": position, "type_name": type_name,
                    "ongoing_only": ongoing_only, "sort": sort, "direction": direction}})


@app.get("/players", response_class=HTMLResponse)
def page_players(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "players.html", {"active": "players", **queries.players_index(connection)})


@app.get("/player/{player_id}", response_class=HTMLResponse)
def page_player(request: Request, player_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "player.html", {"active": "injuries", **queries.player_timeline(connection, player_id)})


@app.get("/leagues", response_class=HTMLResponse)
def page_leagues(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "leagues.html", {"active": "leagues", "leagues": queries.leagues_index(connection)})


@app.get("/league/{league_id}", response_class=HTMLResponse)
def page_league(request: Request, league_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = queries.league_detail(connection, league_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="League not found")
    return templates.TemplateResponse(request, "league.html", {"active": "leagues", **detail})


@app.get("/teams", response_class=HTMLResponse)
def page_teams(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "teams.html", {"active": "teams", "teams": queries.teams_index(connection)})


@app.get("/team/{team_id}", response_class=HTMLResponse)
def page_team(request: Request, team_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = queries.team_detail(connection, team_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return templates.TemplateResponse(request, "team.html", {"active": "teams", **detail})


@app.get("/seasons", response_class=HTMLResponse)
def page_seasons(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "seasons.html", {"active": "seasons", "seasons": queries.seasons_index(connection)})


@app.get("/season/{season_id}", response_class=HTMLResponse)
def page_season(request: Request, season_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = queries.season_detail(connection, season_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Season not found")
    return templates.TemplateResponse(request, "season.html", {"active": "seasons", **detail})


@app.get("/types", response_class=HTMLResponse)
def page_types(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "types.html", {"active": "types", "types": queries.types_index(connection)})


@app.get("/type/{type_id}", response_class=HTMLResponse)
def page_type(request: Request, type_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        detail = queries.type_detail(connection, type_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Injury type not found")
    return templates.TemplateResponse(request, "type.html", {"active": "types", **detail})
