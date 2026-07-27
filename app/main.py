"""Thin FastAPI routes over the testable injury query layer."""
import os

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
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
def api_injuries(country: str | None = None, position: str | None = None, type_name: str | None = None,
                 ongoing_only: bool = False, sort: str = "start_date", direction: str = "desc",
                 page: int = 1, per_page: int = 50, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return queries.injury_list(connection, country, position, type_name, ongoing_only, sort, direction, page, per_page)


@app.get("/api/player/{player_id}")
def api_player(player_id: int, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return queries.player_timeline(connection, player_id)


@app.get("/", response_class=HTMLResponse)
def page_coverage(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "coverage.html", {"active": "coverage", "overview": queries.overview(connection), "quality": queries.quality_metrics(connection), "coverage": queries.coverage_by_league(connection)})


@app.get("/analytics", response_class=HTMLResponse)
def page_analytics(request: Request, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "analytics.html", {"active": "analytics", "by_position": queries.by_position(connection), "by_age_band": queries.by_age_band(connection), "by_type": queries.by_type(connection), "by_nationality": queries.by_nationality(connection), "by_league": queries.by_league(connection), "by_month": queries.by_month(connection)})


@app.get("/injuries", response_class=HTMLResponse)
def page_injuries(request: Request, country: str | None = None, position: str | None = None,
                  type_name: str | None = None, ongoing_only: bool = False, sort: str = "start_date",
                  direction: str = "desc", page: int = 1, _: str = Depends(verify_auth)):
    with _connection() as connection:
        return templates.TemplateResponse(request, "injuries.html", {"active": "injuries", "result": queries.injury_list(connection, country, position, type_name, ongoing_only, sort, direction, page), "options": queries.filter_options(connection), "filters": {"country": country, "position": position, "type_name": type_name, "ongoing_only": ongoing_only, "sort": sort, "direction": direction}})


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
