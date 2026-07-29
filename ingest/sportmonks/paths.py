"""Filesystem layout for the raw cache and reference data.

Centralised so every runner agrees on where cached responses live — the
cache is the durable record of everything downloaded, so its location is not
something to duplicate and risk diverging.
"""
import json
import os

# Three levels up: ingest/sportmonks/paths.py -> ingest/sportmonks -> ingest ->
# repo root. If this module ever moves depth again, this must move with it: a
# wrong BASE does not raise, it silently reads and writes a parallel cache tree
# that looks empty rather than broken.
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RAW_ROOT = os.path.join(BASE, "data", "raw", "sportmonks")
FIXTURES_DIR = os.path.join(RAW_ROOT, "fixtures")
PLAYERS_DIR = os.path.join(RAW_ROOT, "players")
TEAMS_DIR = os.path.join(RAW_ROOT, "teams")
SQUADS_DIR = os.path.join(RAW_ROOT, "squads")
TYPES_FILE = os.path.join(RAW_ROOT, "types.json")
COUNTRIES_FILE = os.path.join(RAW_ROOT, "countries.json")

WATERMARK_FILE = os.path.join(RAW_ROOT, "watermark.json")
REFERENCE_DIR = os.path.join(BASE, "data", "reference", "sportmonks")
COVERAGE_FILE = os.path.join(REFERENCE_DIR, "coverage_uefa55.json")
ENTITIES_FILE = os.path.join(REFERENCE_DIR, "entities.json")

COVERAGE_DB = os.path.join(BASE, "coverage.db")
LOG_DIR = os.path.join(BASE, "logs")

FOOTBALL = "https://api.sportmonks.com/v3/football"
CORE = "https://api.sportmonks.com/v3/core"


def fixture_cache_path(league_id, year_month):
    """Cache key for one (league, month) fixture window: e.g. 271_2024-03.json."""
    return os.path.join(FIXTURES_DIR, f"{league_id}_{year_month}.json")


def entity_cache_path(kind, entity_id):
    """Cache key for one resolved entity: e.g. players/12345.json."""
    return os.path.join(RAW_ROOT, kind, f"{entity_id}.json")


def squad_cache_path(team_id):
    """Cache key for one team's squad roster: e.g. squads/2447.json."""
    return os.path.join(SQUADS_DIR, f"{team_id}.json")


def load_leagues():
    """The 53 UEFA leagues with their corrected Sportmonks ids.

    Reads the same reference file the original sweep used. Raises if it's
    missing rather than silently sweeping zero leagues.
    """
    if not os.path.exists(COVERAGE_FILE):
        raise FileNotFoundError(f"league reference file missing: {COVERAGE_FILE}")
    with open(COVERAGE_FILE, encoding="utf-8") as handle:
        return json.load(handle).get("leagues", [])
