"""Phase 0 recon for API-Football: plan limits + the injury-coverage work list.

Two API calls, and they can invalidate the rest of the ingestion plan — so this
runs before any runner is written.

1. `GET /status`  — authoritative plan name, daily limit, and calls used today.
   Every rate-limit figure we hold so far comes from free-tier headers and the
   published plan table; this is what makes them real.
2. `GET /leagues` — one call returns every league, every season, and each
   season's `coverage` object (including the boolean `injuries`). This single
   response IS the crawl's work list.

The question this answers: **does API-Football expose domestic seasons older
than 2024?** Sportmonks' domestic history is hard-capped at 3 seasons, so if
API-Football is also shallow it adds breadth and a cross-check, but not the
history we're missing. Cheap to find out; expensive to assume.

Read-only: fetches, caches, reports. Writes no database and mutates nothing.

Usage:
    uv run python scripts/apifootball/af_status_and_coverage.py
    uv run python scripts/apifootball/af_status_and_coverage.py --refresh
    uv run python scripts/apifootball/af_status_and_coverage.py --all-seasons
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE, "data", "raw", "apifootball")
REFERENCE_DIR = os.path.join(BASE, "data", "reference", "apifootball")
LOG_DIR = os.path.join(BASE, "logs")

API = "https://v3.football.api-sports.io"

# Free tier is ~10 req/min; Pro is far higher. Two calls either way, so pace
# conservatively rather than reading the plan we haven't fetched yet.
MIN_INTERVAL = 7.0

# The 55 UEFA member associations' top-tier leagues, as (country, name_hint).
# Country match is MANDATORY — an early run matched three different countries
# to Scotland's "Premiership" on name alone and attributed real records to the
# wrong nations. The hint only disambiguates *within* a country.
# Liechtenstein has no domestic league; its clubs play in the Swiss pyramid.
UEFA55 = [
    ("Albania", "Superliga"), ("Andorra", "1a Divisió"),
    ("Armenia", "Premier League"), ("Austria", "Bundesliga"),
    ("Azerbaijan", "Premyer Liqa"), ("Belarus", "Premier League"),
    ("Belgium", "Jupiler Pro League"), ("Bosnia", "Premijer Liga"),
    ("Bulgaria", "First League"), ("Croatia", "HNL"),
    ("Cyprus", "1. Division"), ("Czech-Republic", "Czech Liga"),
    ("Denmark", "Superliga"), ("England", "Premier League"),
    ("Estonia", "Meistriliiga"), ("Faroe-Islands", "Premier League"),
    ("Finland", "Veikkausliiga"), ("France", "Ligue 1"),
    ("Georgia", "Erovnuli Liga"), ("Germany", "Bundesliga"),
    ("Gibraltar", "Premier Division"), ("Greece", "Super League 1"),
    ("Hungary", "NB I"), ("Iceland", "Úrvalsdeild"),
    ("Israel", "Ligat Ha'al"), ("Italy", "Serie A"),
    ("Kazakhstan", "Premier League"), ("Kosovo", "Superliga"),
    ("Latvia", "Virsliga"), ("Liechtenstein", None),
    ("Lithuania", "A Lyga"), ("Luxembourg", "National Division"),
    ("Malta", "Premier League"), ("Moldova", "Super Liga"),
    ("Montenegro", "First League"), ("Netherlands", "Eredivisie"),
    ("Macedonia", "First League"), ("Northern-Ireland", "Premiership"),
    ("Norway", "Eliteserien"), ("Poland", "Ekstraklasa"),
    ("Portugal", "Primeira Liga"), ("Ireland", "Premier Division"),
    ("Romania", "Liga I"), ("Russia", "Premier League"),
    ("San-Marino", "Campionato"), ("Scotland", "Premiership"),
    ("Serbia", "Super Liga"), ("Slovakia", "Super Liga"),
    ("Slovenia", "1. SNL"), ("Spain", "La Liga"),
    ("Sweden", "Allsvenskan"), ("Switzerland", "Super League"),
    ("Turkey", "Süper Lig"), ("Ukraine", "Premier League"),
    ("Wales", "Premier League"),
]

# UEFA club competitions. These carry country "World", NOT a member nation, so
# the country-matched UEFA55 sweep above cannot see them. On the Sportmonks side
# exactly this blind spot hid all four competitions — ~30,000 sidelined rows and
# the deepest history in that dataset — behind a truthful-looking "nothing to
# fetch" (logbook/sportmonks.md, 2026-07-27). Matched by name within the
# non-national catalogue rather than by hardcoded id, so a renamed or re-ided
# competition surfaces as unresolved instead of silently vanishing.
UEFA_CLUB_COMPETITIONS = [
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Europa Conference League",
    "UEFA Super Cup",
]

RECENT_SEASONS = [2023, 2024, 2025]


# --------------------------------------------------------------------------- #
# HTTP — paced, logged, cache-first. Concurrency is deliberately absent: this
# phase makes two calls. The Phase 2/3 runners are where parallelism pays.
# --------------------------------------------------------------------------- #
def log_response(log_path, url, params, response, elapsed):
    """Append the full response as one JSON line. The key lives in a header,
    which we never log — but redact defensively in case that ever changes."""
    try:
        body = response.json()
    except ValueError:
        body = {"_non_json_text": response.text[:4000]}
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
        "params": {k: v for k, v in (params or {}).items() if "key" not in k.lower()},
        "status": response.status_code,
        "elapsed_s": round(elapsed, 3),
        "headers": {k: v for k, v in response.headers.items()
                    if k.lower().startswith("x-ratelimit")},
        "body": body,
    }
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def fetch(session, log_path, path, params=None, state=None):
    """GET one endpoint, paced and logged. Returns (status, body, headers)."""
    state = state if state is not None else {}
    elapsed_since = time.monotonic() - state.get("last", 0.0)
    if elapsed_since < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed_since)
    url = f"{API}{path}"
    start = time.monotonic()
    response = session.get(url, params=params or {}, timeout=30)
    state["last"] = time.monotonic()
    log_response(log_path, url, params, response, time.monotonic() - start)
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body, response.headers


def read_cache(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_cache(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2)


def cached_fetch(session, log_path, path, cache_name, refresh, state):
    """Cache-first fetch: a cached response is never re-fetched.

    Same discipline as the Sportmonks pipeline — the raw response is written to
    disk before any processing, so a download is never lost to a later failure.
    """
    cache_path = os.path.join(RAW_DIR, cache_name)
    if not refresh:
        cached = read_cache(cache_path)
        if cached is not None:
            print(f"  {cache_name}: cache hit (use --refresh to re-fetch)")
            return cached, True
    status, body, headers = fetch(session, log_path, path, state=state)
    if status != 200 or body is None:
        print(f"  ! {path} returned HTTP {status}")
        if body:
            print(f"    {str(body)[:300]}")
        return None, False
    errors = body.get("errors")
    if errors and (errors if isinstance(errors, (list, dict)) else True):
        # API-Football signals plan/auth problems in a 200 body, not the status.
        if isinstance(errors, dict) and errors:
            print(f"  ! {path} returned errors: {errors}")
            return None, False
    write_cache(cache_path, body)
    report_quota(headers)
    return body, False


def report_quota(headers):
    day_left = headers.get("x-ratelimit-requests-remaining")
    day_limit = headers.get("x-ratelimit-requests-limit")
    min_left = headers.get("X-RateLimit-Remaining")
    min_limit = headers.get("X-RateLimit-Limit")
    if day_left is not None:
        print(f"  quota headers: {day_left}/{day_limit} today · "
              f"{min_left}/{min_limit} this minute")


# --------------------------------------------------------------------------- #
# Reporting.
# --------------------------------------------------------------------------- #
def report_status(body):
    """Print the authoritative plan + usage from /status."""
    data = (body or {}).get("response") or {}
    account = data.get("account") or {}
    subscription = data.get("subscription") or {}
    requests_info = data.get("requests") or {}
    print("\n### Plan (authoritative, from /status)\n")
    name = account.get("firstname") or account.get("email") or "—"
    print(f"  account       : {name}")
    print(f"  plan          : {subscription.get('plan')}")
    print(f"  active        : {subscription.get('active')}")
    print(f"  ends          : {subscription.get('end')}")
    print(f"  requests today: {requests_info.get('current')} / "
          f"{requests_info.get('limit_day')}")
    return requests_info.get("limit_day")


def norm(value):
    return (value or "").strip().lower().replace("-", " ")


def resolve_uefa55(items):
    """Match each UEFA top-tier league in the /leagues payload.

    Country match is mandatory. Within a country we prefer an EXACT normalised
    name match before falling back to substring — a substring-first match
    silently picks second divisions ("Erovnuli Liga 2", "1 Lyga").
    """
    resolved, unresolved = [], []
    for country, hint in UEFA55:
        candidates = [
            it for it in items
            if norm((it.get("country") or {}).get("name")) == norm(country)
            and (it.get("league") or {}).get("type") == "League"
        ]
        chosen = None
        if hint and candidates:
            for it in candidates:
                if norm(it["league"]["name"]) == norm(hint):
                    chosen = it
                    break
            if chosen is None:
                for it in candidates:
                    if norm(hint) in norm(it["league"]["name"]):
                        chosen = it
                        break
        if chosen is None and candidates and hint is None:
            chosen = None  # Liechtenstein: no domestic league, expected
        if chosen is None and candidates and hint:
            chosen = candidates[0]
        if chosen:
            resolved.append((country, chosen))
        else:
            unresolved.append(country)

    # Continental competitions, matched by name across the whole catalogue.
    # Their `country` is "World", so the loop above structurally cannot find
    # them — they need their own pass, not a wider country list.
    for name in UEFA_CLUB_COMPETITIONS:
        chosen = None
        for item in items:
            if norm((item.get("league") or {}).get("name")) == norm(name):
                chosen = item
                break
        if chosen:
            resolved.append(("(UEFA club)", chosen))
        else:
            unresolved.append(name)
    return resolved, unresolved


def injury_seasons(league_item):
    """Season years where coverage.injuries is true, ascending."""
    years = []
    for season in league_item.get("seasons") or []:
        if ((season.get("coverage") or {}).get("injuries")):
            year = season.get("year")
            if year is not None:
                years.append(year)
    return sorted(years)


def format_seasons(years, show_all=False):
    """Render a season list without implying coverage it doesn't have.

    `2020..2025 (2)` reads as a six-season range when it is in fact two seasons
    somewhere inside that span — a gap the reader cannot see. Only collapse to
    a range when the years are genuinely contiguous; otherwise list them.
    """
    if not years:
        return "— none —"
    if len(years) == 1:
        return str(years[0])
    contiguous = years == list(range(min(years), max(years) + 1))
    if contiguous and not show_all:
        return f"{min(years)}–{max(years)} ({len(years)})"
    return ",".join(str(y) for y in years)


def report_coverage(resolved, unresolved, show_all):
    """The season-depth table — the output that decides the ingestion plan."""
    print("\n### Injury coverage by UEFA top-tier league "
          "(from coverage.injuries)\n")
    rows = []
    for country, item in resolved:
        league = item["league"]
        years = injury_seasons(item)
        rows.append((country, league["name"], league["id"], years))

    width = max([len("Country")] + [len(r[0]) for r in rows]) if rows else 20
    print(f"| {'Country'.ljust(width)} | id    | seasons with injuries |")
    print(f"|{'-' * (width + 2)}|-------|-----------------------|")
    for country, _name, league_id, years in rows:
        summary = format_seasons(years, show_all)
        print(f"| {country.ljust(width)} | {league_id:<5} | {summary:<21} |")

    covered = [r for r in rows if r[3]]
    dark = [r for r in rows if not r[3]]
    print(f"\nCOVERED: {len(covered)}/{len(rows)} resolved leagues have injury "
          f"data in at least one season")
    if dark:
        print(f"DARK   : {', '.join(r[0] for r in dark)}")
    if unresolved:
        print(f"UNRESOLVED: {', '.join(unresolved)} "
              f"(Liechtenstein has no domestic league — expected)")

    # The decisive question: how far back does DOMESTIC history actually go?
    print("\n### History depth — the question that drives the plan\n")
    earliest = {}
    for country, _name, _lid, years in covered:
        for year in years:
            earliest.setdefault(year, []).append(country)
    for year in sorted(earliest):
        names = earliest[year]
        shown = ", ".join(sorted(names)[:6])
        more = f" +{len(names) - 6} more" if len(names) > 6 else ""
        print(f"  {year}: {len(names):2} leagues — {shown}{more}")

    pre_2024 = sorted(y for y in earliest if y < 2024)
    if pre_2024:
        print(f"\n  API-Football DOES expose pre-2024 injury seasons "
              f"({pre_2024[0]}..2023). This is history Sportmonks cannot give "
              f"(its domestic seasons are capped at 2024/25+).")
    else:
        print("\n  No pre-2024 injury coverage found. API-Football adds "
              "BREADTH and a cross-check, NOT history — same domestic wall as "
              "Sportmonks. Plan framing should change accordingly.")
    return rows


def write_reference(rows, limit_day):
    """Persist the work list Phase 1/2 will iterate."""
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "GET /leagues (coverage.injuries flag)",
        "daily_limit": limit_day,
        "note": "Flag-derived. Verified accurate for 2023/24 on 2026-07-23; "
                "2025+ not yet count-confirmed.",
        "leagues": [
            {"country": country, "league": name, "id": league_id,
             "injury_seasons": years}
            for country, name, league_id, years in rows
        ],
    }
    path = os.path.join(REFERENCE_DIR, "coverage.json")
    write_cache(path, payload)
    print(f"\nwork list -> {path}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="API-Football Phase 0 recon: plan limits + coverage map")
    parser.add_argument("--refresh", action="store_true",
                        help="ignore the cache and re-fetch both endpoints")
    parser.add_argument("--all-seasons", action="store_true",
                        help="list every covered season instead of a range")
    args = parser.parse_args(argv)

    load_dotenv()
    key = os.getenv("APIFOOTBALL_KEY")
    if not key or key.startswith("REPLACE_"):
        print("! APIFOOTBALL_KEY not set in .env")
        return 1

    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(LOG_DIR, f"apifootball-phase0.{stamp}.log")
    print(f"logging responses -> {log_path}")

    session = requests.Session()
    session.headers.update({"x-apisports-key": key})
    state = {"last": 0.0}

    print("\nfetching /status …")
    status_body, _ = cached_fetch(session, log_path, "/status", "status.json",
                                  args.refresh, state)
    limit_day = report_status(status_body) if status_body else None

    print("\nfetching /leagues …")
    leagues_body, _ = cached_fetch(session, log_path, "/leagues", "leagues.json",
                                   args.refresh, state)
    if not leagues_body:
        print("! cannot build the coverage map without /leagues")
        return 1

    items = leagues_body.get("response") or []
    print(f"  {len(items)} leagues in the catalogue")

    resolved, unresolved = resolve_uefa55(items)
    rows = report_coverage(resolved, unresolved, args.all_seasons)
    write_reference(rows, limit_day)

    print("\nNext: record the history-depth finding in logbook/apifootball.md "
          "before building any runner on top of it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
