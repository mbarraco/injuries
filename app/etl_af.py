"""Build apifootball.db from the raw API-Football cache.

Mirrors `app/etl.py` in role — read the cache, produce a queryable database —
but not in schema, because the vendors differ structurally (see
`app/schema_af.sql` for why).

The database is a rebuildable artifact; the raw cache under
`data/raw/apifootball/` is the durable record. Throw this away and re-run it
any time.

**Two preconditions are enforced before anything is written**, because both
failure modes produce plausible wrong numbers rather than errors:

1. **No cache file may be flagged `truncated`.** A truncated /players file means
   a truncated minutes denominator, which inflates every injury rate computed
   from it. This actually happened: 16 files capped at 1,000 records cost
   ~18,500 player-seasons in the biggest leagues, and the crawl reported
   `{'ok': 117}` throughout.
2. **Every distinct `reason` must map to an `af_reason` row.** `af_injury`
   joins that table, so an unmapped reason silently vanishes from the view
   rather than surfacing as uncategorised.

Usage:
    uv run python -m app.etl_af
    uv run python -m app.etl_af --allow-truncated   # escape hatch, states it
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, "data", "raw", "apifootball")
SCHEMA = os.path.join(BASE, "app", "schema_af.sql")
DB_PATH = os.path.join(BASE, "app", "apifootball.db")

# Reason classification, derived from the 205 distinct values measured
# 2026-07-29. Ordered most-specific-first: a reason is tested against
# SUSPENSION and ADMIN markers before INJURY, because "Suspended (red card)"
# should not be caught by a generic injury match.
#
# Deliberately conservative: anything unmatched becomes 'unknown' and stays
# visible in af_reason with its row count, rather than being folded into
# 'injury' to make a total look tidy.
# Markers are STEMS, not whole words. This bit three times in one session:
# "suspend" does not match "Suspension" (suspen-d vs suspen-s-ion), just as
# "day" does not match "daily". Prefer the shortest unambiguous stem.
SUSPENSION_MARKERS = (
    "suspen",          # suspend / suspended / suspension
    # "banned", not "ban": suspension and admin markers are tested BEFORE
    # injury ones, so a loose stem here misfiles real injuries — "ban" would
    # swallow "bandage".
    "red card", "yellow card", "banned", "sanction", "ineligib")
ADMIN_MARKERS = (
    "national selection", "national team", "international duty", "inactive",
    "lacking match fitness", "personal reason", "rest", "coach's decision",
    "not in squad", "transfer", "contract", "doping", "loan", "administrative",
    "visa", "quarantine")
INJURY_MARKERS = (
    "injur", "knock", "strain", "tear", "torn", "fractur", "broken", "break",
    "sprain", "surger", "operation", "ill", "virus", "covid", "concussion",
    "bruise", "contusion", "inflamm", "itis", "pain", "problem", "discomfort",
    "fatigue", "cramp", "dead leg", "muscular", "fitness", "unfit",
    # Added after the first build left 639 rows unclassified, ~590 of them
    # plainly injuries. Each of these was measured in the real data.
    "wound", "convalescen", "hernia", "disorder", "complaint", "cartilage",
    "overload", "pubalgia", "heart condition", "infection", "appendect",
    "laceration", "stress response", "damage", "rupture", "dislocat",
    "trauma", "sick", "fever", "flu", "abscess", "thrombo", "swelling")

# Body parts, longest-first so "achilles tendon" wins over "tendon".
BODY_PARTS = (
    "achilles tendon", "cruciate ligament", "hamstring", "adductor", "meniscus",
    "shoulder", "abdominal", "collarbone", "metatarsal", "ligament", "tendon",
    "ankle", "thigh", "groin", "knee", "calf", "back", "foot", "hip", "head",
    "neck", "rib", "arm", "toe", "leg", "eye", "jaw", "hand", "wrist", "elbow",
    "chest", "nose", "muscle", "shin", "heel", "pelvis", "buttock", "finger")


def classify_reason(reason):
    """Return (category, body_part). Category: injury|suspension|administrative|unknown."""
    lowered = (reason or "").strip().lower()
    if not lowered:
        return "unknown", None
    body_part = next((part for part in BODY_PARTS if part in lowered), None)
    for marker in SUSPENSION_MARKERS:
        if marker in lowered:
            return "suspension", None
    for marker in ADMIN_MARKERS:
        if marker in lowered:
            return "administrative", None
    for marker in INJURY_MARKERS:
        if marker in lowered:
            return "injury", body_part
    # A bare body part with no other signal ("Knee", "Ankle") is an injury.
    if body_part:
        return "injury", body_part
    return "unknown", None


# Transfer type classification, from the 12 distinct category values and 112
# distinct fee strings measured 2026-07-30. `type` is a THREE-way mixed field:
# one column carries a category word, a fee, or a null-marker.
#
# Exact matching on the lowered string, NOT substring: the values are short and
# a substring test would make "Free agent" match under "Free". Synonym clusters
# are collapsed here and only here.
TRANSFER_CATEGORIES = {
    "loan": "loan",
    # Three vendor spellings of one concept.
    "return from loan": "loan_return",
    "back from loan": "loan_return",
    "end of loan": "loan_return",
    "free": "free",
    "free transfer": "free",
    # NOT folded into 'free': this is a signing made while unattached, which is
    # a different fact about the player than a fee-free move between two clubs.
    "free agent": "free_agent",
    # A paid move whose fee the vendor did not disclose. Distinct from 'unknown'
    # -- we know money changed hands, we just don't know how much. Collapsing
    # the two would make "fee undisclosed" and "no idea" indistinguishable.
    "transfer": "undisclosed",
    "swap": "swap",
    # 21% of rows. NOT "no transfer happened" -- often an unlabelled loan
    # return. Anything asserting a category for these is inventing one.
    "n/a": "unknown",
    "-": "unknown",
    "": "unknown",
    # Meaning undetermined. Left as 'unknown' rather than guessed: 7 rows in the
    # sample, and a wrong guess here is invisible in every downstream total.
    "raise": "unknown",
}

# Fee strings, in the three formats measured. All euros in the sample, but the
# sample was two European clubs, so a non-euro symbol must NOT be silently
# treated as euros -- an unconverted dollar fee summed into a euro total is
# undetectable. `$` and `£` therefore parse an amount with no fee_eur.
_FEE_PATTERN = re.compile(
    r"""^\s*
        (?P<sym1>[€$£])?\s*
        (?P<num>\d+(?:[.,]\d+)?)\s*
        (?P<mult>[KMkm])?\s*
        (?P<sym2>[€$£])?
        \s*$""", re.VERBOSE)

_MULTIPLIER = {"k": 1_000, "m": 1_000_000}
_CURRENCY = {"€": "EUR", "$": "USD", "£": "GBP"}


def classify_transfer_type(raw):
    """Return (category, fee_amount, fee_currency, fee_eur, fee_format).

    Category words are matched first and exactly, so a stray digit in a future
    category value cannot be mistaken for a fee.
    """
    text = (raw or "").strip()
    lowered = text.lower()
    if lowered in TRANSFER_CATEGORIES:
        return TRANSFER_CATEGORIES[lowered], None, None, None, None

    match = _FEE_PATTERN.match(text)
    if not match:
        # A value that is neither a known category nor a parseable fee. Kept
        # visible as 'unknown' with its row count rather than dropped, so a new
        # vendor value shows up in af_transfer_type instead of quietly becoming
        # a gap in every fee total.
        return "unknown", None, None, None, None

    number = float(match.group("num").replace(",", "."))
    multiplier = _MULTIPLIER.get((match.group("mult") or "").lower(), 1)
    amount = int(round(number * multiplier))

    symbol = match.group("sym1") or match.group("sym2")
    currency = _CURRENCY.get(symbol)
    if match.group("sym1"):
        fee_format = "sym_num"
    elif match.group("sym2"):
        fee_format = "num_sym"
    else:
        fee_format = "bare"
    # fee_eur is populated ONLY for euros. A bare "2.6M" has a known amount and
    # an unstated denomination; that distinction is the whole point of keeping
    # three columns instead of one.
    fee_eur = amount if currency == "EUR" else None
    return "fee", amount, currency, fee_eur, fee_format


# --------------------------------------------------------------------------- #
# Cache reading.
# --------------------------------------------------------------------------- #
def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def cache_files(subdir):
    return sorted(glob.glob(os.path.join(RAW, subdir, "*.json")))


def check_truncation():
    """Every league-season cache file flagged as incomplete."""
    flagged = []
    for subdir in ("injuries", "fixtures", "teams", "standings", "players"):
        for path in cache_files(subdir):
            if (read_json(path) or {}).get("truncated"):
                flagged.append(f"{subdir}/{os.path.basename(path)}")
    return flagged


# --------------------------------------------------------------------------- #
# Collectors — each returns plain dicts/lists, so they are unit-testable
# without a database.
# --------------------------------------------------------------------------- #
def collect_leagues_and_seasons():
    """League dimension + the (league, season) link table, from the work list."""
    leagues, pairs = {}, []
    coverage_path = os.path.join(BASE, "data", "reference", "apifootball",
                                 "coverage.json")
    coverage = read_json(coverage_path) if os.path.exists(coverage_path) else {}
    for entry in coverage.get("leagues", []):
        leagues[entry["id"]] = {"id": entry["id"], "name": entry.get("league"),
                                "country": entry.get("country")}
        for season in entry.get("injury_seasons") or []:
            pairs.append((entry["id"], season, 1))
    return leagues, pairs


def collect_teams():
    teams = {}
    for path in cache_files("teams"):
        for record in read_json(path).get("teams") or []:
            team = record.get("team") or {}
            venue = record.get("venue") or {}
            if not team.get("id"):
                continue
            teams[team["id"]] = {
                "id": team["id"], "name": team.get("name"),
                "country": team.get("country"), "founded": team.get("founded"),
                "code": team.get("code"), "venue_id": venue.get("id"),
                "venue_name": venue.get("name"), "venue_city": venue.get("city"),
                "venue_capacity": venue.get("capacity"),
            }
    return teams


def collect_players_and_seasons():
    """Player dimension plus per (player, league, season, team) playing time.

    `position` and `minutes` both live on the statistics blocks, not the player
    root -- the vendor reports them per competition-season, which is more honest
    than a single career value since players move and change role.
    """
    players, seasons = {}, {}
    for path in cache_files("players"):
        for record in read_json(path).get("players") or []:
            player = record.get("player") or {}
            pid = player.get("id")
            if not pid:
                continue
            birth = player.get("birth") or {}
            players[pid] = {
                "id": pid, "name": player.get("name"),
                "firstname": player.get("firstname"),
                "lastname": player.get("lastname"),
                "birth_date": birth.get("date"),
                "birth_country": birth.get("country"),
                "nationality": player.get("nationality"),
                "height_cm": _first_int(player.get("height")),
                "weight_kg": _first_int(player.get("weight")),
            }
            for block in record.get("statistics") or []:
                team = (block.get("team") or {}).get("id")
                league = (block.get("league") or {}).get("id")
                season = (block.get("league") or {}).get("season")
                if not (team and league and season is not None):
                    continue
                games = block.get("games") or {}
                seasons[(pid, league, season, team)] = {
                    "player_id": pid, "league_id": league, "season": season,
                    "team_id": team, "position": games.get("position"),
                    "appearances": games.get("appearences"),  # vendor's spelling
                    "lineups": games.get("lineups"),
                    "minutes": games.get("minutes"),
                    "rating": _as_float(games.get("rating")),
                }
    return players, seasons


def _first_int(value):
    """'180 cm' -> 180. Height and weight arrive as strings with units."""
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def collect_fixtures():
    fixtures = {}
    for path in cache_files("fixtures"):
        for record in read_json(path).get("fixtures") or []:
            fixture = record.get("fixture") or {}
            if not fixture.get("id"):
                continue
            league = record.get("league") or {}
            teams = record.get("teams") or {}
            goals = record.get("goals") or {}
            venue = fixture.get("venue") or {}
            status = fixture.get("status") or {}
            fixtures[fixture["id"]] = {
                "id": fixture["id"], "league_id": league.get("id"),
                "season": league.get("season"), "date": fixture.get("date"),
                "timestamp": fixture.get("timestamp"),
                "status_short": status.get("short"), "round": league.get("round"),
                "venue_name": venue.get("name"), "referee": fixture.get("referee"),
                "home_team_id": (teams.get("home") or {}).get("id"),
                "away_team_id": (teams.get("away") or {}).get("id"),
                "goals_home": goals.get("home"), "goals_away": goals.get("away"),
            }
    return fixtures


def collect_absences():
    """Absence rows at the vendor's own grain: one per (player, fixture).

    No deduplication and no spell reconstruction. A multi-match absence stays N
    rows here because that is what the vendor supplied; collapsing it would
    require inventing spell boundaries, and that inference moves 75% across
    plausible thresholds (logbook 2026-07-29).
    """
    rows, reasons = [], Counter()
    for path in cache_files("injuries"):
        for record in read_json(path).get("injuries") or []:
            player = record.get("player") or {}
            team = record.get("team") or {}
            fixture = record.get("fixture") or {}
            league = record.get("league") or {}
            reason = (player.get("reason") or "").strip()
            reasons[reason] += 1
            rows.append({
                "player_id": player.get("id"), "fixture_id": fixture.get("id"),
                "team_id": team.get("id"), "league_id": league.get("id"),
                "season": league.get("season"), "type": player.get("type"),
                "reason": reason, "fixture_date": fixture.get("date"),
            })
    return rows, reasons


def _sharded_cache_files(subdir):
    """Transfer and fixture-detail caches are sharded one level deep."""
    return sorted(glob.glob(os.path.join(RAW, subdir, "*", "*.json")))


def collect_transfers():
    """Career transfer rows, deduplicated across both crawl subjects.

    Returns (rows, type_counts, stats).

    **Dedup is explicit and counted, not a constraint.** Two reasons, both
    measured (logbook 2026-07-30):

    1. The vendor emits true duplicates. Player 19034 had two byte-identical
       rows for `2020-08-01 Ajax->Galatasaray`. A UNIQUE constraint on the
       documented natural key would abort the build or silently drop rows.
    2. A move between two covered clubs is reported three times over: once by
       each club's team file and once by the player's file. That is agreement,
       not new information -- but only if it is collapsed deliberately and the
       collapse is counted. Left alone it triple-counts the busiest clubs.

    `source` records which subjects saw a row, so agreement stays visible rather
    than being flattened away by the dedup that relies on it.
    """
    merged, stats = {}, Counter()
    for subject, subdir in (("team", "transfers_team"),
                            ("player", "transfers_player")):
        files = _sharded_cache_files(subdir)
        stats[f"{subject}_files"] = len(files)
        for path in files:
            for entry in read_json(path).get("transfers") or []:
                player = (entry or {}).get("player") or {}
                for move in (entry or {}).get("transfers") or []:
                    teams = (move or {}).get("teams") or {}
                    out_side = teams.get("out") or {}
                    in_side = teams.get("in") or {}
                    raw_type = (move or {}).get("type")
                    # The identity of the FACT, deliberately excluding `source`:
                    # the same move seen from a club and from the player is one
                    # transfer, not two.
                    key = (player.get("id"), (move or {}).get("date"), raw_type,
                           out_side.get("id"), in_side.get("id"))
                    stats["raw_rows"] += 1
                    existing = merged.get(key)
                    if existing is None:
                        merged[key] = {
                            "player_id": player.get("id"),
                            "player_name": player.get("name"),
                            "date": (move or {}).get("date"),
                            "type": (raw_type or "").strip(),
                            "from_team_id": out_side.get("id"),
                            "from_team_name": out_side.get("name"),
                            "to_team_id": in_side.get("id"),
                            "to_team_name": in_side.get("name"),
                            "source": subject,
                        }
                    else:
                        stats["collapsed"] += 1
                        if existing["source"] != subject:
                            existing["source"] = "both"
                            stats["confirmed_by_both"] += 1
                        else:
                            stats["duplicate_within_subject"] += 1

    rows = list(merged.values())
    type_counts = Counter(row["type"] for row in rows)
    stats["rows"] = len(rows)
    # An id-less club side is not an error -- the vendor sometimes puts a PLAYER
    # name in the club field ("Icardi Mauro"). Counted so the number is on the
    # record and the app knows how many sides it must render as plain text.
    stats["sides_without_id"] = sum(
        1 for row in rows for key in ("from_team_id", "to_team_id")
        if row[key] is None)
    return rows, type_counts, stats


# --------------------------------------------------------------------------- #
# Loading.
# --------------------------------------------------------------------------- #
def create_db(path=DB_PATH):
    if os.path.exists(path):
        os.remove(path)
    connection = sqlite3.connect(path)
    with open(SCHEMA, encoding="utf-8") as handle:
        connection.executescript(handle.read())
    return connection


def insert_many(connection, table, columns, rows):
    if not rows:
        return 0
    placeholders = ",".join("?" * len(columns))
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    connection.executemany(sql, [[row.get(column) for column in columns]
                                 for row in rows])
    return len(rows)


def load(connection, allow_truncated=False):
    counts = {}

    truncated = check_truncation()
    if truncated:
        message = (f"{len(truncated)} cache file(s) are TRUNCATED and therefore "
                   f"incomplete:\n  " + "\n  ".join(truncated[:10]))
        if not allow_truncated:
            raise SystemExit(
                f"! {message}\n\n"
                f"  Refusing to build: a truncated /players file means a "
                f"truncated minutes\n  denominator, which INFLATES every injury "
                f"rate derived from it — silently.\n  Fix with:\n"
                f"    uv run python -m ingest.apifootball.crawl "
                f"--target players --refresh-truncated\n"
                f"  Or pass --allow-truncated to build anyway (the "
                f"af_data_quality table\n  will record that the build was "
                f"knowingly incomplete).")
        print(f"! WARNING: building with {message}")

    leagues, league_seasons = collect_leagues_and_seasons()
    counts["league"] = insert_many(connection, "af_league",
                                   ["id", "name", "country"], list(leagues.values()))
    connection.executemany(
        "INSERT OR REPLACE INTO af_league_season (league_id, season, has_injuries)"
        " VALUES (?,?,?)", league_seasons)
    counts["league_season"] = len(league_seasons)

    teams = collect_teams()
    counts["team"] = insert_many(
        connection, "af_team",
        ["id", "name", "country", "founded", "code", "venue_id", "venue_name",
         "venue_city", "venue_capacity"], list(teams.values()))

    players, player_seasons = collect_players_and_seasons()
    counts["player"] = insert_many(
        connection, "af_player",
        ["id", "name", "firstname", "lastname", "birth_date", "birth_country",
         "nationality", "height_cm", "weight_kg"], list(players.values()))
    counts["player_season"] = insert_many(
        connection, "af_player_season",
        ["player_id", "league_id", "season", "team_id", "position",
         "appearances", "lineups", "minutes", "rating"],
        list(player_seasons.values()))

    fixtures = collect_fixtures()
    counts["fixture"] = insert_many(
        connection, "af_fixture",
        ["id", "league_id", "season", "date", "timestamp", "status_short",
         "round", "venue_name", "referee", "home_team_id", "away_team_id",
         "goals_home", "goals_away"], list(fixtures.values()))

    absences, reason_counts = collect_absences()
    # af_reason MUST be populated before the invariant check, and must cover
    # every distinct reason -- including '' and anything unclassifiable, which
    # land as 'unknown' rather than being dropped.
    reason_rows = []
    for reason, count in reason_counts.items():
        category, body_part = classify_reason(reason)
        reason_rows.append({"reason": reason, "category": category,
                            "body_part": body_part, "row_count": count})
    counts["reason"] = insert_many(
        connection, "af_reason",
        ["reason", "category", "body_part", "row_count"], reason_rows)

    counts["absence"] = insert_many(
        connection, "af_absence",
        ["player_id", "fixture_id", "team_id", "league_id", "season", "type",
         "reason", "fixture_date"], absences)

    # Transfers are optional: the crawl is separate and may not have run. An
    # empty tree yields zero rows rather than an error, so a build before the
    # transfer crawl still succeeds -- but the counts say plainly that it is
    # zero rather than omitting the tables and making absence look like presence.
    transfers, type_counts, transfer_stats = collect_transfers()
    # af_transfer_type MUST be populated before the rows, and must cover every
    # distinct type -- same contract as af_reason, for the same reason:
    # af_transfer_detail joins it.
    type_rows = []
    for raw_type, count in type_counts.items():
        category, amount, currency, fee_eur, fee_format = classify_transfer_type(raw_type)
        type_rows.append({"type": raw_type, "category": category,
                          "fee_amount": amount, "fee_currency": currency,
                          "fee_eur": fee_eur, "fee_format": fee_format,
                          "row_count": count})
    counts["transfer_type"] = insert_many(
        connection, "af_transfer_type",
        ["type", "category", "fee_amount", "fee_currency", "fee_eur",
         "fee_format", "row_count"], type_rows)
    counts["transfer"] = insert_many(
        connection, "af_transfer",
        ["player_id", "player_name", "date", "type", "from_team_id",
         "from_team_name", "to_team_id", "to_team_name", "source"], transfers)

    connection.commit()
    return counts, reason_counts, truncated, transfer_stats


def verify(connection, truncated):
    """Assert the invariants the schema documents. Returns a list of problems."""
    problems = []

    unmapped = connection.execute(
        "SELECT COUNT(*) FROM af_unmapped_reason").fetchone()[0]
    if unmapped:
        problems.append(
            f"{unmapped} distinct reason(s) have no af_reason row — af_injury "
            f"is silently under-reporting. Query af_unmapped_reason.")

    orphan_fixtures = connection.execute(
        "SELECT COUNT(*) FROM af_absence a LEFT JOIN af_fixture f "
        "ON f.id = a.fixture_id WHERE f.id IS NULL").fetchone()[0]
    if orphan_fixtures:
        # Not fatal, but name WHERE they come from rather than just counting:
        # injuries and fixtures were fetched from the same 117-pair work list,
        # so a gap means the two endpoints disagree about which fixtures exist
        # in a league-season — worth knowing, not worth blocking a build over.
        detail = connection.execute(
            "SELECT a.league_id, a.season, COUNT(*) FROM af_absence a "
            "LEFT JOIN af_fixture f ON f.id = a.fixture_id "
            "WHERE f.id IS NULL GROUP BY a.league_id, a.season "
            "ORDER BY 3 DESC LIMIT 5").fetchall()
        where = ", ".join(f"league {lid} season {s} ({n})" for lid, s, n in detail)
        problems.append(f"{orphan_fixtures} absence row(s) reference a fixture "
                        f"not in af_fixture — {where}. The /injuries and "
                        f"/fixtures endpoints disagree for these league-seasons.")

    orphan_players = connection.execute(
        "SELECT COUNT(DISTINCT a.player_id) FROM af_absence a "
        "LEFT JOIN af_player p ON p.id = a.player_id "
        "WHERE p.id IS NULL").fetchone()[0]
    if orphan_players:
        # Expected to be non-zero and NOT a defect: /players returns players
        # with statistics for a league-season, so someone injured for a whole
        # season may never appear there. Their absences are still real and must
        # be kept — the player page simply cannot show playing time.
        problems.append(f"{orphan_players} player(s) with absences have no "
                        f"af_player row (injured all season, so absent from "
                        f"/players). Their absences are kept; rates for them "
                        f"have no denominator.")

    types = dict(connection.execute(
        "SELECT type, COUNT(*) FROM af_absence GROUP BY type").fetchall())
    unexpected = set(types) - {"Missing Fixture", "Questionable"}
    if unexpected:
        problems.append(f"unexpected absence type(s): {sorted(unexpected)} — "
                        f"the schema's assumptions about `type` need revisiting.")

    unmapped_type = connection.execute(
        "SELECT COUNT(*) FROM af_unmapped_transfer_type").fetchone()[0]
    if unmapped_type:
        problems.append(
            f"{unmapped_type} distinct transfer type(s) have no "
            f"af_transfer_type row — af_transfer_detail is dropping them. "
            f"Query af_unmapped_transfer_type.")

    # A new fee format would parse as 'unknown' and vanish from every fee total
    # without erroring. Surfacing the unknown share is what makes that visible;
    # the sampled baseline was 21% (almost all of it the vendor's own 'N/A').
    transfer_rows = connection.execute(
        "SELECT COUNT(*) FROM af_transfer").fetchone()[0]
    if transfer_rows:
        unknown_share = connection.execute(
            "SELECT COUNT(*) FROM af_transfer_detail "
            "WHERE category = 'unknown'").fetchone()[0] / transfer_rows
        if unknown_share > 0.35:
            problems.append(
                f"{unknown_share:.1%} of transfers have category 'unknown' — "
                f"well above the ~21% measured baseline, which is mostly the "
                f"vendor's own 'N/A'. A new type or fee format is probably "
                f"unparsed; check af_transfer_type ORDER BY row_count DESC.")

        # Non-euro fees are parsed but deliberately left out of fee_eur. If any
        # appear, every euro total silently excludes them, and that must be said
        # out loud rather than discovered later.
        other_currency = connection.execute(
            "SELECT fee_currency, SUM(row_count) FROM af_transfer_type "
            "WHERE fee_currency IS NOT NULL AND fee_currency <> 'EUR' "
            "GROUP BY fee_currency").fetchall()
        if other_currency:
            detail = ", ".join(f"{cur} ({n} rows)" for cur, n in other_currency)
            problems.append(
                f"non-euro transfer fees present: {detail}. These carry "
                f"fee_amount but NOT fee_eur, so any euro total excludes them.")

    if truncated:
        problems.append(f"built from {len(truncated)} TRUNCATED cache file(s) — "
                        f"minutes and therefore any rate are understated.")
    return problems


def write_data_quality(connection, counts, reason_counts, truncated,
                       transfer_stats=None):
    metrics = [(f"rows_{table}", float(count), None)
               for table, count in counts.items()]

    types = connection.execute(
        "SELECT type, COUNT(*) FROM af_absence GROUP BY type").fetchall()
    for name, count in types:
        metrics.append((f"absence_type_{name.replace(' ', '_').lower()}",
                        float(count), "absence rows"))

    categories = connection.execute(
        "SELECT r.category, COUNT(*) FROM af_absence a "
        "JOIN af_reason r ON r.reason = a.reason GROUP BY r.category").fetchall()
    for name, count in categories:
        metrics.append((f"absence_category_{name}", float(count), "absence rows"))

    minutes_rows = connection.execute(
        "SELECT COUNT(*) FROM af_player_season WHERE minutes IS NOT NULL"
    ).fetchone()[0]
    total_ps = counts.get("player_season", 0) or 1
    metrics.append(("player_season_minutes_fill", minutes_rows / total_ps,
                    "share of player-seasons with a minutes value"))

    metrics.append(("distinct_reasons", float(len(reason_counts)), None))
    metrics.append(("truncated_source_files", float(len(truncated)),
                    "non-zero means rates are understated"))
    metrics.append(("absence_grain", 0.0,
                    "rows are (player, fixture) appearances, NOT spells — no "
                    "spell id exists in this vendor's data"))

    # Transfers. Every one of these is a number that would otherwise only exist
    # in a run's scrollback, and the dedup counts in particular are the audit
    # trail for a step that deliberately deletes rows.
    for name, value in (transfer_stats or {}).items():
        metrics.append((f"transfer_{name}", float(value), {
            "raw_rows": "move rows read from cache, before dedup",
            "rows": "distinct moves kept",
            "collapsed": "rows dropped as duplicates of a kept row",
            "confirmed_by_both": "moves reported by BOTH a club and the player",
            "duplicate_within_subject": "true vendor duplicates, identical rows "
                                        "from the same subject",
            "sides_without_id": "club sides with a name but no id — the vendor "
                                "sometimes puts a PLAYER here; render as text, "
                                "never as a link",
            "team_files": "cached /transfers?team= responses",
            "player_files": "cached /transfers?player= responses",
        }.get(name)))

    if counts.get("transfer"):
        transfer_categories = connection.execute(
            "SELECT category, COUNT(*) FROM af_transfer_detail "
            "GROUP BY category").fetchall()
        for name, count in transfer_categories:
            metrics.append((f"transfer_category_{name}", float(count),
                            "transfer rows"))
        fee_rows, fee_total = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(fee_eur), 0) FROM af_transfer_detail "
            "WHERE fee_eur IS NOT NULL").fetchone()
        metrics.append(("transfer_fee_eur_rows", float(fee_rows),
                        "rows with a euro fee — the rest are free, loans, "
                        "undisclosed, or unparsed"))
        metrics.append(("transfer_fee_eur_total", float(fee_total),
                        "sum of PARSED euro fees only; inferred from a mixed "
                        "text field, never a vendor-supplied total"))
        earliest, latest = connection.execute(
            "SELECT MIN(date), MAX(date) FROM af_transfer "
            "WHERE date IS NOT NULL").fetchone()
        metrics.append(("transfer_date_span", 0.0,
                        f"{earliest} .. {latest} — NOT capped at 2020-2025 like "
                        f"every other table here"))
        metrics.append(("transfer_date_precision", 0.0,
                        "trustworthy to the SEASON, not the day: dates cluster "
                        "on 07-01 and on batch-stamped days"))

    connection.executemany(
        "INSERT OR REPLACE INTO af_data_quality (metric, value, detail) "
        "VALUES (?,?,?)", metrics)
    connection.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build apifootball.db from the raw cache")
    parser.add_argument("--allow-truncated", action="store_true",
                        help="build even if source files are incomplete; records "
                             "the fact in af_data_quality")
    args = parser.parse_args(argv)

    if not os.path.isdir(RAW):
        print(f"! no cache at {RAW}")
        return 1

    print(f"building {DB_PATH}")
    connection = create_db()
    counts, reason_counts, truncated, transfer_stats = load(
        connection, args.allow_truncated)

    connection.execute(
        "INSERT INTO af_ingest_run (run_at, source_file_count, notes) VALUES (?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
         sum(len(cache_files(d)) for d in
             ("injuries", "fixtures", "teams", "players", "standings"))
         + transfer_stats.get("team_files", 0)
         + transfer_stats.get("player_files", 0),
         f"truncated_sources={len(truncated)}"))
    write_data_quality(connection, counts, reason_counts, truncated,
                       transfer_stats)

    print("\nrows loaded:")
    for table, count in counts.items():
        print(f"  {table:16} {count:>9,}")

    print("\nreason categories:")
    for category, count in connection.execute(
            "SELECT r.category, COUNT(*) FROM af_absence a "
            "JOIN af_reason r ON r.reason = a.reason "
            "GROUP BY r.category ORDER BY 2 DESC").fetchall():
        print(f"  {category:16} {count:>9,}")

    print("\nabsence types (never sum these):")
    for name, count in connection.execute(
            "SELECT type, COUNT(*) FROM af_absence GROUP BY type "
            "ORDER BY 2 DESC").fetchall():
        print(f"  {name:16} {count:>9,}")

    if counts.get("transfer"):
        print("\ntransfer categories:")
        for category, count in connection.execute(
                "SELECT category, COUNT(*) FROM af_transfer_detail "
                "GROUP BY category ORDER BY 2 DESC").fetchall():
            print(f"  {str(category):16} {count:>9,}")
        earliest, latest = connection.execute(
            "SELECT MIN(date), MAX(date) FROM af_transfer "
            "WHERE date IS NOT NULL").fetchone()
        print(f"\ntransfer history spans {earliest} .. {latest} "
              f"(NOT capped at 2020–2025 like every other table)")
        print(f"  dedup: {transfer_stats['raw_rows']:,} rows read → "
              f"{transfer_stats['rows']:,} distinct "
              f"({transfer_stats.get('collapsed', 0):,} collapsed, of which "
              f"{transfer_stats.get('confirmed_by_both', 0):,} were the same "
              f"move seen from both a club and the player)")
        fee_rows, fee_total = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(fee_eur), 0) FROM af_transfer_detail "
            "WHERE fee_eur IS NOT NULL").fetchone()
        print(f"  fees: {fee_rows:,} rows carry a parsed euro fee, "
              f"€{fee_total:,} total — INFERRED from a mixed text field")
    else:
        print("\nno transfers cached — af_transfer is empty. Fetch with:\n"
              "  uv run python -m ingest.apifootball.transfers --target team")

    problems = verify(connection, truncated)
    if problems:
        print("\n! INVARIANT PROBLEMS:")
        for problem in problems:
            print(f"    {problem}")
    else:
        print("\nall invariants hold.")

    connection.close()
    return 1 if problems and not args.allow_truncated else 0


if __name__ == "__main__":
    sys.exit(main())
