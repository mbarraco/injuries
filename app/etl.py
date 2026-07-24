"""Build the curated application database without needing vendor access."""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RAW_DIR = os.path.join(BASE, "data", "raw", "sportmonks", "fixtures")
DEFAULT_REFERENCE_DB = os.path.join(BASE, "coverage.db")
DEFAULT_OUT_DB = os.path.join(BASE, "app", "app.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
INJURY_CATEGORY = "injury"


def collect_absences(raw_dir):
    """Deduplicate fixture appearances into one absence per sideline id.

    The fixture feed repeats an absence once for each missed match; sorted
    processing makes the first observed league attribution deterministic.
    """
    absences = {}
    files = sorted(glob.glob(os.path.join(raw_dir, "*.json")))
    for path in files:
        with open(path, encoding="utf-8") as source:
            document = json.load(source)
        for fixture in document.get("fixtures", []):
            for pivot in fixture.get("sidelined") or []:
                sideline = pivot.get("sideline") or {}
                sideline_id = pivot.get("sideline_id") or sideline.get("id")
                if not sideline_id:
                    continue
                if sideline_id in absences:
                    absences[sideline_id]["fixture_appearances"] += 1
                    continue
                absences[sideline_id] = {
                    "id": sideline_id,
                    "player_id": sideline.get("player_id") or pivot.get("player_id"),
                    "team_id": sideline.get("team_id"),
                    "type_id": sideline.get("type_id") or pivot.get("type_id"),
                    "category": sideline.get("category"),
                    "season_id": fixture.get("season_id"),
                    "league_id": document.get("league_id"),
                    "start_date": sideline.get("start_date"),
                    "end_date": sideline.get("end_date"),
                    "games_missed": sideline.get("games_missed"),
                    "completed": sideline.get("completed"),
                    "fixture_appearances": 1,
                }
    return absences, len(files)


def _parse_date(value):
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date() if value else None
    except ValueError:
        return None


def derive_fields(absence, birth_date):
    """Materialize analytics fields once, instead of recalculating per view."""
    start_date = _parse_date(absence["start_date"])
    end_date = _parse_date(absence["end_date"])
    birth = _parse_date(birth_date)
    duration = (end_date - start_date).days if start_date and end_date else None
    age = round((start_date - birth).days / 365.25, 1) if start_date and birth else None
    return duration, age, int(end_date is None)


def _write_quality_metrics(connection, absences, injuries, excluded, file_count):
    raw_rows = sum(item["fixture_appearances"] for item in absences.values())
    distinct = len(absences)
    metrics = [
        ("source_files", file_count, "cached fixture-month JSON files scanned"),
        ("raw_pivot_rows", raw_rows, "fixture appearances before deduplication"),
        ("distinct_absences", distinct, "unique sideline_id values"),
        ("dedup_ratio", round(raw_rows / distinct, 2) if distinct else 0, "raw rows per absence"),
        ("injuries", len(injuries), "category == 'injury'"),
    ]
    metrics.extend(
        (f"excluded_{category}", count, f"category '{category}' excluded")
        for category, count in sorted(excluded.items())
    )
    if injuries:
        for index, field in ((2, "team_id"), (7, "end_date"), (8, "games_missed")):
            populated = sum(row[index] is not None for row in injuries)
            metrics.append((f"fill_{field}", round(100 * populated / len(injuries), 1),
                            f"% of injuries with {field} populated"))
    connection.executemany("INSERT INTO data_quality VALUES (?, ?, ?)", metrics)


def build(raw_dir=DEFAULT_RAW_DIR, reference_db=DEFAULT_REFERENCE_DB, out_db=DEFAULT_OUT_DB):
    """Rebuild app.db from cached raw fixtures and resolved reference data."""
    absences, file_count = collect_absences(raw_dir)
    if os.path.exists(out_db):
        os.remove(out_db)
    connection = sqlite3.connect(out_db)
    with open(SCHEMA_PATH, encoding="utf-8") as schema:
        connection.executescript(schema.read())
    reference = sqlite3.connect(f"file:{reference_db}?mode=ro", uri=True)
    try:
        players = {int(row[0]): row for row in reference.execute(
            "SELECT id, name, position, detailed_position, nationality, date_of_birth, height_cm, weight_kg FROM sportmonks_player"
        )}
        connection.executemany("INSERT INTO player VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               [(int(row[0]), *row[1:]) for row in players.values()])
        connection.executemany("INSERT INTO team VALUES (?, ?, ?, ?, ?)",
                               [(int(row[0]), *row[1:]) for row in reference.execute(
                                   "SELECT id, name, country, founded, short_code FROM sportmonks_team")])
        connection.executemany("INSERT INTO injury_type VALUES (?, ?)",
                               [(int(row[0]), row[1]) for row in reference.execute("SELECT id, name FROM sportmonks_type")])
        seasons = list(reference.execute(
            "SELECT id, league_id, country, league_name, name, is_current FROM sportmonks_season"))
        connection.executemany("INSERT OR IGNORE INTO league VALUES (?, ?, ?)",
                               sorted({(int(row[1]), row[2], row[3]) for row in seasons if row[1]}))
        connection.executemany("INSERT INTO season VALUES (?, ?, ?, ?)",
                               [(int(row[0]), int(row[1]) if row[1] else None, row[4], row[5]) for row in seasons])
        connection.executemany("INSERT INTO league_coverage VALUES (?, ?, ?, ?, ?, ?)",
                               [(row[0], row[1], int(row[2]) if row[2] else None, row[3], row[4], row[5])
                                for row in reference.execute(
                                    "SELECT country, league, sportmonks_id, year_bucket, record_count, tier FROM sportmonks_coverage WHERE run_id = 16")])

        injuries, excluded = [], {}
        for absence in absences.values():
            if absence["category"] != INJURY_CATEGORY:
                category = absence["category"] or "unknown"
                excluded[category] = excluded.get(category, 0) + 1
                continue
            player = players.get(absence["player_id"])
            duration, age, ongoing = derive_fields(absence, player[5] if player else None)
            injuries.append((
                absence["id"], absence["player_id"], absence["team_id"], absence["league_id"],
                absence["season_id"], absence["type_id"], absence["start_date"], absence["end_date"],
                absence["games_missed"], int(bool(absence["completed"])), absence["fixture_appearances"],
                duration, age, ongoing,
            ))
        connection.executemany("INSERT INTO injury VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", injuries)
        _write_quality_metrics(connection, absences, injuries, excluded, file_count)
        connection.execute("INSERT INTO ingest_run (run_at, source_file_count, notes) VALUES (?, ?, ?)",
                           (datetime.now(timezone.utc).isoformat(timespec="seconds"), file_count,
                            "rebuilt from raw cache"))
        connection.commit()
        return {"injuries": len(injuries), "excluded": excluded}
    finally:
        connection.close()
        reference.close()


if __name__ == "__main__":
    result = build()
    print(f"injuries loaded: {result['injuries']}")
    print(f"excluded by category: {result['excluded']}")
    print(f"-> {DEFAULT_OUT_DB}")
