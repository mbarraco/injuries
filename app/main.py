"""Thin FastAPI routes over the testable injury query layer.

Page routes live in sportmonks_routes.py and af_routes.py, one router per
vendor, mirroring each other. This module keeps only app setup and the
/api/* JSON contract, which is frozen and never moves -- AGENTS.md documents
that external callers depend on /api/injuries specifically, and this app
extends that same caution to the whole /api/* family.
"""
import os

from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import af_queries, af_routes, db, queries, sportmonks_routes
from app.auth import verify_auth

HERE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Injury Data POC")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
# Additive: each vendor lives under its own prefix, its own database, its own
# query layer. Shares auth, static assets and the base layout/macros only.
app.include_router(sportmonks_routes.router)
app.include_router(af_routes.router)


def _connection():
    return db.connect()


def _category_or_none(value):
    """"all" (the UI's plain-form choice for "no filter") becomes None."""
    return None if value in (None, "", "all") else value


@app.get("/", response_class=HTMLResponse)
def page_home(request: Request, _: str = Depends(verify_auth)):
    """The neutral landing page: two peer cards, one per vendor, neither
    styled as primary. Deliberately sets no `active` value that starts with
    'sportmonks-' or 'af-', so base.html's vendor derivation leaves data-vendor
    unset here -- each card scopes its own accent locally instead."""
    with db.connect() as connection:
        sportmonks_overview = queries.overview(connection)
    with db.connect_af() as connection:
        af_overview = af_queries.overview(connection)
    return templates.TemplateResponse(request, "home.html", {
        "active": "home", "sportmonks": sportmonks_overview, "af": af_overview})


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
