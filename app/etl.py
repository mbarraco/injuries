"""Build the curated application database without needing vendor access."""
from __future__ import annotations

import glob
import json
import os
import sqlite3
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RAW_DIR = os.path.join(BASE, "data", "raw", "sportmonks", "fixtures")
DEFAULT_PLAYERS_DIR = os.path.join(BASE, "data", "raw", "sportmonks", "players")
DEFAULT_REFERENCE_DB = os.path.join(BASE, "coverage.db")
DEFAULT_OUT_DB = os.path.join(BASE, "app", "app.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

# Sportmonks stat type_ids (resolved from the cached types taxonomy) for the
# playing-time metrics that make injury *rate* computable.
STAT_MINUTES, STAT_APPEARANCES, STAT_LINEUPS = 119, 321, 322


def collect_absences(raw_dir):
    """Deduplicate fixture appearances into one absence per sideline id.

    The fixture feed repeats an absence once for each missed match; sorted
    processing makes the first observed league attribution deterministic.
    """
    absences = {}
    # Sidelined density per year, for the coverage-ramp metrics. The vendor's
    # historical coverage improves steadily over time (no absence records exist
    # before 2006 at all), so raw yearly counts describe Sportmonks' backfill
    # effort, not football. Measured here so the app can surface the caveat.
    fixtures_by_year, sidelined_by_year = {}, {}
    files = sorted(glob.glob(os.path.join(raw_dir, "*.json")))
    for path in files:
        with open(path, encoding="utf-8") as source:
            document = json.load(source)
        # Filename is {league_id}_{YYYY-MM}.json — the window queried, which is
        # what we want here regardless of individual fixture timestamps.
        year = os.path.basename(path).split("_")[-1][:4]
        for fixture in document.get("fixtures", []):
            fixtures_by_year[year] = fixtures_by_year.get(year, 0) + 1
            sidelined_by_year[year] = (sidelined_by_year.get(year, 0)
                                       + len(fixture.get("sidelined") or []))
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
    return absences, len(files), fixtures_by_year, sidelined_by_year


def _stat_total(details, type_id):
    """The `total` of one stat metric, or None if absent/malformed."""
    value = details.get(type_id)
    return value.get("total") if isinstance(value, dict) else None


def collect_player_seasons(players_dir):
    """Per-(player, season, team) playing time from the enriched player cache.

    Only players re-fetched with include=statistics.details carry a
    `statistics` array; players still on the thin fetch (or a not-yet-run
    enrichment) simply contribute nothing, so this degrades gracefully during
    a partial enrichment run rather than failing.
    """
    rows = []
    for path in sorted(glob.glob(os.path.join(players_dir, "*.json"))):
        with open(path, encoding="utf-8") as source:
            player = json.load(source)
        for line in player.get("statistics") or []:
            details = {item.get("type_id"): item.get("value") for item in line.get("details") or []}
            rows.append((
                line.get("player_id"), line.get("season_id"), line.get("team_id"),
                _stat_total(details, STAT_MINUTES), _stat_total(details, STAT_APPEARANCES),
                _stat_total(details, STAT_LINEUPS),
            ))
    return rows


def collect_transfers(players_dir):
    """Career transfers from the enriched player cache, deduplicated by id.

    Like collect_player_seasons, only players re-fetched with the `transfers`
    include contribute; others are silently absent, so a partial enrichment
    run still produces a consistent table.
    """
    by_id = {}
    for path in sorted(glob.glob(os.path.join(players_dir, "*.json"))):
        with open(path, encoding="utf-8") as source:
            player = json.load(source)
        for transfer in player.get("transfers") or []:
            transfer_id = transfer.get("id")
            if transfer_id is None or transfer_id in by_id:
                continue  # first occurrence wins — don't let a later partial row clobber it
            by_id[transfer_id] = (
                transfer_id, transfer.get("player_id"), transfer.get("from_team_id"),
                transfer.get("to_team_id"), transfer.get("date"), transfer.get("type_id"),
                transfer.get("amount"), int(bool(transfer.get("completed"))),
                int(bool(transfer.get("career_ended"))),
            )
    return list(by_id.values())


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


def _write_coverage_metrics(connection, fixtures_by_year, sidelined_by_year):
    """Sidelined records per fixture, per year — the dataset's biggest caveat.

    This ratio climbs from 0.00 (no absence records exist before 2006) to ~4
    today. That is the vendor's historical coverage improving, NOT a real-world
    injury trend, so any year-on-year comparison of injury counts measures
    Sportmonks' backfill rather than football. Recorded per year so the
    distortion is visible and correctable instead of silently wrong.

    Caveat worth carrying with the number: the competition mix is not constant.
    Domestic leagues only exist here from 2024 (the plan sells 3 seasons), so
    earlier years are UEFA cups alone. The 2023->2024 step therefore blends a
    coverage change with a mix change and shouldn't be attributed to either.
    """
    metrics = []
    for year in sorted(fixtures_by_year):
        fixtures = fixtures_by_year[year]
        density = round(sidelined_by_year.get(year, 0) / fixtures, 2) if fixtures else 0
        metrics.append((f"coverage_{year}", density,
                        f"sidelined rows per fixture in {year} ({fixtures} fixtures) — "
                        f"vendor coverage, not injury rate; pre-2024 is cups-only"))
    connection.executemany("INSERT INTO data_quality VALUES (?, ?, ?)", metrics)


def _write_quality_metrics(connection, absences, rows, category_counts, file_count):
    """Record measured coverage/quality numbers for the app to render.

    Nothing is excluded any more (every category is stored), so the metrics
    describe the full absence set plus a per-category breakdown. Field-fill
    rates are still measured over injuries only, since those are the records
    the app's analytics actually lean on.
    """
    raw_rows = sum(item["fixture_appearances"] for item in absences.values())
    distinct = len(absences)
    injuries = [row for row in rows if row[6] == "injury"]
    metrics = [
        ("source_files", file_count, "cached fixture-month JSON files scanned"),
        ("raw_pivot_rows", raw_rows, "fixture appearances before deduplication"),
        ("distinct_absences", distinct, "unique sideline_id values"),
        ("dedup_ratio", round(raw_rows / distinct, 2) if distinct else 0, "raw rows per absence"),
        ("injuries", len(injuries), "category == 'injury'"),
    ]
    metrics.extend(
        (f"category_{category}", count, f"distinct absences with category '{category}'")
        for category, count in sorted(category_counts.items())
    )
    if injuries:
        # absence tuple layout: team_id[2], end_date[8], games_missed[9].
        for index, field in ((2, "team_id"), (8, "end_date"), (9, "games_missed")):
            populated = sum(row[index] is not None for row in injuries)
            metrics.append((f"fill_{field}", round(100 * populated / len(injuries), 1),
                            f"% of injuries with {field} populated"))
    connection.executemany("INSERT INTO data_quality VALUES (?, ?, ?)", metrics)


def build(raw_dir=DEFAULT_RAW_DIR, reference_db=DEFAULT_REFERENCE_DB, out_db=DEFAULT_OUT_DB,
          players_dir=None):
    """Rebuild app.db from cached raw fixtures and resolved reference data.

    `players_dir`, when given, is scanned for enriched player JSON to populate
    the `player_season` table (playing time per season). Left None by callers
    that don't need it (e.g. tests), so the player_season table stays empty.
    """
    absences, file_count, fixtures_by_year, sidelined_by_year = collect_absences(raw_dir)
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

        rows, category_counts = [], {}
        for absence in absences.values():
            category = absence["category"] or "unknown"
            category_counts[category] = category_counts.get(category, 0) + 1
            player = players.get(absence["player_id"])
            duration, age, ongoing = derive_fields(absence, player[5] if player else None)
            rows.append((
                absence["id"], absence["player_id"], absence["team_id"], absence["league_id"],
                absence["season_id"], absence["type_id"], category, absence["start_date"],
                absence["end_date"], absence["games_missed"], int(bool(absence["completed"])),
                absence["fixture_appearances"], duration, age, ongoing,
            ))
        connection.executemany(
            "INSERT INTO absence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

        player_seasons = collect_player_seasons(players_dir) if players_dir else []
        if player_seasons:
            connection.executemany(
                "INSERT OR IGNORE INTO player_season VALUES (?, ?, ?, ?, ?, ?)", player_seasons)
            connection.executemany("INSERT INTO data_quality VALUES (?, ?, ?)", [
                ("player_season_rows", len(player_seasons), "per-player-season stat lines from enriched cache"),
                ("players_with_stats", len({row[0] for row in player_seasons}), "distinct players with season stats"),
            ])
        transfers = collect_transfers(players_dir) if players_dir else []
        if transfers:
            connection.executemany(
                "INSERT OR IGNORE INTO transfer VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", transfers)
            connection.execute("INSERT INTO data_quality VALUES (?, ?, ?)",
                               ("transfer_rows", len(transfers), "distinct transfer records from enriched cache"))
        _write_quality_metrics(connection, absences, rows, category_counts, file_count)
        _write_coverage_metrics(connection, fixtures_by_year, sidelined_by_year)
        connection.execute("INSERT INTO ingest_run (run_at, source_file_count, notes) VALUES (?, ?, ?)",
                           (datetime.now(timezone.utc).isoformat(timespec="seconds"), file_count,
                            "rebuilt from raw cache"))
        connection.commit()
        injuries = category_counts.get("injury", 0)
        return {"absences": len(rows), "injuries": injuries, "categories": category_counts,
                "player_seasons": len(player_seasons), "transfers": len(transfers)}
    finally:
        connection.close()
        reference.close()


if __name__ == "__main__":
    result = build(players_dir=DEFAULT_PLAYERS_DIR)
    print(f"absences loaded: {result['absences']} (injuries: {result['injuries']})")
    print(f"by category: {result['categories']}")
    print(f"player-season stat rows: {result['player_seasons']}")
    print(f"transfer rows: {result['transfers']}")
    print(f"-> {DEFAULT_OUT_DB}")
