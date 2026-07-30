"""Filesystem layout for the API-Football raw cache and reference data.

Centralised so every runner agrees on where cached responses live — the cache
is the durable record of everything downloaded, so its location is not
something to duplicate and risk diverging.

Mirrors `ingest/sportmonks/paths.py` in role, but the cache keys differ because
the APIs are shaped differently: Sportmonks caches one file per (league,
*month*) because absences ride on fixtures fetched by date window;
API-Football caches one file per (league, *season*) because injuries and
fixtures are both addressable that way directly.
"""
import json
import os

# Four levels up: ingest/apifootball/paths.py -> apifootball -> ingest -> repo
# root. If this module ever changes depth, this must change with it: a wrong
# BASE does not raise, it silently reads and writes a parallel cache tree that
# looks empty rather than broken. (That exact bug bit the scripts/ move.)
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RAW_ROOT = os.path.join(BASE, "data", "raw", "apifootball")

# Per (league, season).
INJURIES_DIR = os.path.join(RAW_ROOT, "injuries")
FIXTURES_DIR = os.path.join(RAW_ROOT, "fixtures")
TEAMS_DIR = os.path.join(RAW_ROOT, "teams")
STANDINGS_DIR = os.path.join(RAW_ROOT, "standings")
PLAYERS_DIR = os.path.join(RAW_ROOT, "players")

# Per (league, season, team).
TEAM_STATS_DIR = os.path.join(RAW_ROOT, "team_statistics")

# Per fixture — the long tail. Four endpoints x ~40,000 fixtures, so these
# directories hold the overwhelming majority of the cache by file count.
FIXTURE_EVENTS_DIR = os.path.join(RAW_ROOT, "fixture_events")
FIXTURE_LINEUPS_DIR = os.path.join(RAW_ROOT, "fixture_lineups")
FIXTURE_PLAYERS_DIR = os.path.join(RAW_ROOT, "fixture_players")
FIXTURE_STATS_DIR = os.path.join(RAW_ROOT, "fixture_statistics")

# Transfers, cached under two keys because the endpoint answers two questions
# and neither subsumes the other (logbook 2026-07-30):
#   * by team  — every move in/out of one club, all history. 845 calls total.
#     Measured club-scoped: 704/704 Ajax rows touch Ajax, so this does NOT
#     return the players' wider careers.
#   * by player — one player's complete career, including moves between clubs
#     outside our 47 competitions. The only way to get those.
# Kept in separate trees rather than merged so a re-crawl of one never has to
# reason about which subject produced a given file.
TRANSFERS_TEAM_DIR = os.path.join(RAW_ROOT, "transfers_team")
TRANSFERS_PLAYER_DIR = os.path.join(RAW_ROOT, "transfers_player")

LEAGUES_FILE = os.path.join(RAW_ROOT, "leagues.json")
STATUS_FILE = os.path.join(RAW_ROOT, "status.json")
COUNTRIES_FILE = os.path.join(RAW_ROOT, "countries.json")

REFERENCE_DIR = os.path.join(BASE, "data", "reference", "apifootball")
COVERAGE_FILE = os.path.join(REFERENCE_DIR, "coverage.json")

LOG_DIR = os.path.join(BASE, "logs")


def league_season_path(directory, league_id, season):
    """Cache key for one (league, season) response: e.g. injuries/39_2024.json."""
    return os.path.join(directory, f"{league_id}_{season}.json")


def team_season_path(league_id, season, team_id):
    """Cache key for one (league, season, team) stats response."""
    return os.path.join(TEAM_STATS_DIR, f"{league_id}_{season}_{team_id}.json")


def fixture_path(directory, fixture_id):
    """Cache key for one fixture's detail: e.g. fixture_events/686314.json.

    Sharded two levels deep by the id's last digits. ~40,000 files in a single
    directory is slow to list on most filesystems and painful to inspect by
    hand; four such directories would be worse.
    """
    shard = f"{int(fixture_id) % 100:02d}"
    return os.path.join(directory, shard, f"{fixture_id}.json")


def subject_path(directory, subject_id):
    """Cache key for one transfer subject: e.g. transfers_player/41/276041.json.

    Sharded like `fixture_path` for the same reason — the per-player tree is
    tens of thousands of files. Team transfers use the same helper for
    consistency even though 845 files would be fine flat: one code path means a
    later widening of the team work list cannot outgrow its layout unnoticed.
    """
    shard = f"{int(subject_id) % 100:02d}"
    return os.path.join(directory, shard, f"{subject_id}.json")


def load_coverage():
    """The injury-coverage work list written by Phase 0 recon.

    Raises if missing rather than silently iterating zero leagues — a runner
    that reports "nothing to fetch" is only as trustworthy as the list it
    iterates, and a stale or absent list already cost this project four
    invisible UEFA competitions on the Sportmonks side.
    """
    if not os.path.exists(COVERAGE_FILE):
        raise FileNotFoundError(
            f"coverage work list missing: {COVERAGE_FILE}\n"
            f"Run: uv run python scripts/apifootball/af_status_and_coverage.py")
    with open(COVERAGE_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def covered_league_seasons(coverage=None):
    """Flatten the work list into [(league_id, season, country, league), …].

    One entry per (league, season) pair the vendor flags as having injury
    data — the exact unit every Phase 2/3 runner iterates.
    """
    coverage = coverage or load_coverage()
    pairs = []
    for entry in coverage.get("leagues", []):
        for season in entry.get("injury_seasons") or []:
            pairs.append((entry["id"], season, entry.get("country"),
                          entry.get("league")))
    return pairs
