#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "requests>=2.31,<3",
#     "python-dotenv>=1.0,<2",
# ]
# ///
"""Injury-data coverage probe (v0.1).

Feasibility check: does injury data actually exist for the leagues we care
about, and how far back? Probes API-Football and Sportmonks across a
representative set of leagues (Big 5 + 5 small UEFA nations) and the last
three seasons, stores results in SQLite, and prints a coverage matrix.

This is a throwaway feasibility tool, not an ingestion pipeline.

Usage:
    python probe.py --provider apifootball
    python probe.py --provider sportmonks
    python probe.py --provider both        # default
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

DB_PATH = os.path.join(os.path.dirname(__file__), "coverage.db")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
SEASONS = [2023, 2024, 2025]  # season start years (2023 => 2023/24)

# Probe sets. Each entry is (label, country, name_hint). name_hint disambiguates
# when a country has several leagues; None => pick the country's first top-tier
# one. The probe PRINTS the resolved league name for every target, so wrong-tier
# picks are visible and can be corrected by adjusting the hint.

# Representative sample: Big 5 + 5 small UEFA nations, to expose the cliff.
SAMPLE_TARGETS = [
    ("Premier League (ENG)", "England", "Premier League"),
    ("La Liga (ESP)", "Spain", "La Liga"),
    ("Bundesliga (GER)", "Germany", "Bundesliga"),
    ("Serie A (ITA)", "Italy", "Serie A"),
    ("Ligue 1 (FRA)", "France", "Ligue 1"),
    ("Primera Divisió (AND)", "Andorra", "Divisió"),
    ("Campionato (SMR)", "San Marino", "Campionato"),
    ("Premier League (MLT)", "Malta", "Premier"),
    ("Betri deildin (FRO)", "Faroe Islands", "Premier"),
    ("National League (GIB)", "Gibraltar", "Premier"),
]

# All 55 UEFA member associations' top-tier leagues. Liechtenstein has no
# domestic league (its clubs play in the Swiss pyramid) so it will not resolve.
UEFA55_TARGETS = [
    ("Superiore (ALB)", "Albania", "Superliga"),
    ("1a Divisió (AND)", "Andorra", "Divisió"),
    ("Premier League (ARM)", "Armenia", "Premier"),
    ("Bundesliga (AUT)", "Austria", "Bundesliga"),
    ("Premyer Liqa (AZE)", "Azerbaijan", "Premyer"),
    ("Vysshaya Liga (BLR)", "Belarus", "Premier"),
    ("Pro League (BEL)", "Belgium", "Pro League"),
    ("Premijer Liga (BIH)", "Bosnia", "Premijer"),
    ("First League (BUL)", "Bulgaria", "First"),
    ("HNL (CRO)", "Croatia", "HNL"),
    ("First Division (CYP)", "Cyprus", "Division"),
    ("First League (CZE)", "Czech-Republic", "Liga"),
    ("Superliga (DEN)", "Denmark", "Superliga"),
    ("Premier League (ENG)", "England", "Premier League"),
    ("Meistriliiga (EST)", "Estonia", "Meistriliiga"),
    ("Premier League (FRO)", "Faroe Islands", "Premier"),
    ("Veikkausliiga (FIN)", "Finland", "Veikkausliiga"),
    ("Ligue 1 (FRA)", "France", "Ligue 1"),
    ("Erovnuli Liga (GEO)", "Georgia", "Erovnuli Liga"),
    ("Bundesliga (GER)", "Germany", "Bundesliga"),
    ("National League (GIB)", "Gibraltar", "Premier"),
    ("Super League 1 (GRE)", "Greece", "Super League"),
    ("NB I (HUN)", "Hungary", "NB I"),
    ("Besta deild (ISL)", "Iceland", "deild"),
    ("Ligat ha'Al (ISR)", "Israel", "Ligat"),
    ("Serie A (ITA)", "Italy", "Serie A"),
    ("Premier League (KAZ)", "Kazakhstan", "Premier"),
    ("Superliga (KVX)", "Kosovo", "Superliga"),
    ("Virsliga (LVA)", "Latvia", "Virsliga"),
    ("(no league) (LIE)", "Liechtenstein", None),
    ("A Lyga (LTU)", "Lithuania", "A Lyga"),
    ("National Division (LUX)", "Luxembourg", "National"),
    ("Premier League (MLT)", "Malta", "Premier"),
    ("Super Liga (MDA)", "Moldova", "Super"),
    ("First League (MNE)", "Montenegro", "First"),
    ("Eredivisie (NED)", "Netherlands", "Eredivisie"),
    ("First League (MKD)", "Macedonia", "First"),
    ("Premiership (NIR)", "Northern-Ireland", "Premiership"),
    ("Eliteserien (NOR)", "Norway", "Eliteserien"),
    ("Ekstraklasa (POL)", "Poland", "Ekstraklasa"),
    ("Primeira Liga (POR)", "Portugal", "Primeira"),
    ("Premier Division (IRL)", "Ireland", "Premier"),
    ("Liga I (ROU)", "Romania", "Liga I"),
    ("Premier League (RUS)", "Russia", "Premier"),
    ("Campionato (SMR)", "San Marino", "Campionato"),
    ("Premiership (SCO)", "Scotland", "Premiership"),
    ("Super Liga (SRB)", "Serbia", "Super"),
    ("Super Liga (SVK)", "Slovakia", "Super"),
    ("PrvaLiga (SVN)", "Slovenia", "Prva"),
    ("La Liga (ESP)", "Spain", "La Liga"),
    ("Allsvenskan (SWE)", "Sweden", "Allsvenskan"),
    ("Super League (SUI)", "Switzerland", "Super League"),
    ("Süper Lig (TUR)", "Turkey", "Süper"),
    ("Premier League (UKR)", "Ukraine", "Premier"),
    ("Cymru Premier (WAL)", "Wales", "Cymru"),
]

TARGETS = SAMPLE_TARGETS  # default; overridden by --targets in main()


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS probe_run (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            provider  TEXT NOT NULL,
            run_at    TEXT NOT NULL,
            notes     TEXT
        );
        CREATE TABLE IF NOT EXISTS league (
            provider           TEXT NOT NULL,
            our_label          TEXT NOT NULL,
            country            TEXT,
            provider_league_id TEXT,
            resolved_name      TEXT,
            resolved_ok        INTEGER NOT NULL,
            PRIMARY KEY (provider, our_label)
        );
        CREATE TABLE IF NOT EXISTS coverage (
            run_id             INTEGER NOT NULL,
            provider           TEXT NOT NULL,
            our_label          TEXT NOT NULL,
            provider_league_id TEXT,
            season             TEXT NOT NULL,
            record_count       INTEGER,
            status             TEXT NOT NULL,
            detail             TEXT
        );
        """
    )
    conn.commit()
    return conn


def start_run(conn: sqlite3.Connection, provider: str, notes: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO probe_run (provider, run_at, notes) VALUES (?, ?, ?)",
        (provider, datetime.now(timezone.utc).isoformat(timespec="seconds"), notes),
    )
    conn.commit()
    return int(cur.lastrowid)


def save_league(conn, provider, label, country, pid, name, ok):
    conn.execute(
        "INSERT OR REPLACE INTO league VALUES (?, ?, ?, ?, ?, ?)",
        (provider, label, country, str(pid) if pid is not None else None, name, int(ok)),
    )
    conn.commit()


def save_coverage(conn, run_id, provider, label, pid, season, count, status, detail=""):
    conn.execute(
        "INSERT INTO coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, provider, label, str(pid) if pid is not None else None,
         str(season), count, status, detail),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def cell(count, status):
    if status == "ok":
        return str(count)
    return {
        "empty": "0",
        "not_in_plan": "plan✗",
        "plan_limited": "plan✗",
        "auth_error": "AUTH",
        "rate_limited": "429",
        "unresolved": "—",
        "error": "ERR",
    }.get(status, status)


def print_matrix(provider, rows, columns):
    """rows: list of (label, {col: (count, status)}). columns: list of str."""
    print(f"\n### {provider} — injury coverage matrix\n")
    label_w = max([len("League")] + [len(r[0]) for r in rows])
    header = "| " + "League".ljust(label_w) + " | " + " | ".join(str(c) for c in columns) + " |"
    sep = "|" + "-" * (label_w + 2) + "|" + "|".join("-" * (len(str(c)) + 2) for c in columns) + "|"
    print(header)
    print(sep)
    for label, cols in rows:
        cells = []
        for c in columns:
            count, status = cols.get(c, (None, "error"))
            cells.append(cell(count, status).ljust(len(str(c))))
        print("| " + label.ljust(label_w) + " | " + " | ".join(cells) + " |")
    print("\nLegend: number = injury records found · `0` = reachable but empty · "
          "`plan✗` = not in your plan · `AUTH` = auth failed · `—` = league not resolved\n")


# --------------------------------------------------------------------------- #
# Response logging (one JSON object per line: logs/<provider>.<run>-probe.log)
# --------------------------------------------------------------------------- #
def make_log_path(provider, run_id):
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"{provider}.{run_id}-probe.log")


def _redact(params):
    return {k: ("***" if k == "api_token" else v) for k, v in (params or {}).items()}


def log_response(log_path, provider, url, params, resp, elapsed):
    """Append the full response so runs can be analyzed offline. Never logs tokens."""
    if not log_path:
        return
    try:
        body = resp.json()
    except ValueError:
        body = {"_non_json_text": resp.text[:4000]}
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "url": url,                      # API-Football key is in headers, not here
        "params": _redact(params),       # Sportmonks api_token redacted
        "status": resp.status_code,
        "elapsed_s": round(elapsed, 3),
        "body": body,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# Rate-limit-aware HTTP
# --------------------------------------------------------------------------- #
def polite_get(session, url, params, min_interval, state, max_retries=4):
    """GET with proactive pacing + reactive 429 backoff.

    - min_interval: minimum seconds between calls (stay UNDER the limit).
    - state: dict with "last" monotonic timestamp, mutated in place.
    - On 429: honor Retry-After if present, else exponential backoff, retry.
    """
    elapsed = time.monotonic() - state.get("last", 0.0)
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    r = None
    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        r = session.get(url, params=params, timeout=30)
        state["last"] = time.monotonic()
        log_response(state.get("log"), state.get("provider", "?"), url, params,
                     r, state["last"] - t0)
        if r.status_code != 429:
            return r
        retry_after = r.headers.get("Retry-After")
        wait = int(retry_after) if (retry_after or "").isdigit() else min(60, 15 * (2 ** attempt))
        print(f"    429 rate-limited; waiting {wait}s (retry {attempt + 1}/{max_retries})")
        time.sleep(wait)
    return r  # exhausted retries; return last (still-429) response


# --------------------------------------------------------------------------- #
# API-Football
# --------------------------------------------------------------------------- #
AF_BASE = "https://v3.football.api-sports.io"
# Free tier is ~10 requests/minute -> pace at ~1 per 7s to stay safely under.
# Lower this if you upgrade to a paid plan (300+/min).
AF_MIN_INTERVAL = 7.0
_af_state = {"last": 0.0}


def af_get(session, path, params=None):
    return polite_get(session, f"{AF_BASE}{path}", params or {}, AF_MIN_INTERVAL, _af_state)


def af_report_quota(r):
    """Print remaining daily/per-minute quota from API-Football headers, once."""
    h = r.headers
    day_left = h.get("x-ratelimit-requests-remaining")
    day_limit = h.get("x-ratelimit-requests-limit")
    min_left = h.get("X-RateLimit-Remaining")
    min_limit = h.get("X-RateLimit-Limit")
    if day_left is not None:
        try:
            _af_state["day_left"] = int(day_left)
        except (TypeError, ValueError):
            pass
        print(f"  quota: {day_left}/{day_limit} requests left today · "
              f"{min_left}/{min_limit} left this minute")


def af_resolve_leagues(session, conn):
    """One /leagues call, then match each target by country (+ name hint)."""
    print("API-Football: resolving leagues …")
    r = af_get(session, "/leagues")
    if r.status_code != 200:
        print(f"  ! /leagues returned HTTP {r.status_code}: {r.text[:200]}")
        return {}
    af_report_quota(r)
    payload = r.json()
    items = payload.get("response", [])
    print(f"  fetched {len(items)} leagues")

    def norm(s):
        return (s or "").strip().lower().replace("-", " ")

    resolved = {}  # label -> chosen league item (full dict incl. seasons)
    for label, country, hint in TARGETS:
        candidates = [
            it for it in items
            if norm(it.get("country", {}).get("name")) == norm(country)
            and it.get("league", {}).get("type") == "League"
        ]
        chosen = None
        if hint:
            # 1) exact normalized name match ("Erovnuli Liga" != "Erovnuli Liga 2")
            for it in candidates:
                if norm(it["league"]["name"]) == norm(hint):
                    chosen = it
                    break
            # 2) fall back to substring match
            if chosen is None:
                for it in candidates:
                    if norm(hint) in norm(it["league"]["name"]):
                        chosen = it
                        break
        if chosen is None and candidates:
            chosen = candidates[0]  # smallest-id top-tier league for the country
        if chosen:
            lid = chosen["league"]["id"]
            lname = chosen["league"]["name"]
            resolved[label] = chosen
            save_league(conn, "apifootball", label, country, lid, lname, True)
            print(f"  ✓ {label:26} -> id {lid} ({lname})")
        else:
            save_league(conn, "apifootball", label, country, None, None, False)
            print(f"  ✗ {label:26} -> no top-tier league found for '{country}'")
    return resolved


def af_probe(session, conn, run_id):
    _af_state["provider"] = "apifootball"
    _af_state["log"] = make_log_path("apifootball", run_id)
    print(f"  logging responses -> {_af_state['log']}")
    resolved = af_resolve_leagues(session, conn)

    # Pre-flight quota guard: don't start a run we can't finish today.
    needed = len(resolved) * len(SEASONS)
    day_left = _af_state.get("day_left")
    est_min = (needed * AF_MIN_INTERVAL) / 60.0
    print(f"  plan: {len(resolved)} leagues x {len(SEASONS)} seasons = {needed} "
          f"injury calls (~{est_min:.1f} min at {AF_MIN_INTERVAL:.0f}s pacing)")
    if day_left is not None and needed > day_left:
        print(f"  ! WARNING: run needs {needed} calls but only {day_left} left in "
              f"today's quota. It will hit the daily limit partway and you'll get "
              f"an incomplete map.")
        print(f"  ! Reduce scope: probe one season, e.g. --seasons 2024, "
              f"or wait for the daily reset. Continuing anyway in case you want a "
              f"partial run — Ctrl-C to abort.")

    rows = []
    for label, country, _hint in TARGETS:
        item = resolved.get(label)
        lid = item["league"]["id"] if item else None
        cols = {}
        if lid is None:
            for s in SEASONS:
                cols[s] = (None, "unresolved")
                save_coverage(conn, run_id, "apifootball", label, None, s, None, "unresolved")
            rows.append((label, cols))
            continue
        for s in SEASONS:
            r = af_get(session, "/injuries", {"league": lid, "season": s})  # paced internally
            if r.status_code in (401, 403):
                cols[s] = (None, "auth_error")
                save_coverage(conn, run_id, "apifootball", label, lid, s, None,
                              "auth_error", f"HTTP {r.status_code}")
                continue
            if r.status_code == 429:
                cols[s] = (None, "rate_limited")
                save_coverage(conn, run_id, "apifootball", label, lid, s, None,
                              "rate_limited", "HTTP 429 after retries")
                continue
            if r.status_code != 200:
                cols[s] = (None, "error")
                save_coverage(conn, run_id, "apifootball", label, lid, s, None,
                              "error", f"HTTP {r.status_code}: {r.text[:120]}")
                continue
            body = r.json()
            errors = body.get("errors")
            # API-Football returns errors as {} (ok) or a dict/list with messages.
            if errors and (isinstance(errors, dict) and errors or isinstance(errors, list) and errors):
                cols[s] = (None, "plan_limited")
                save_coverage(conn, run_id, "apifootball", label, lid, s, None,
                              "plan_limited", str(errors)[:200])
                continue
            count = body.get("results", 0)
            status = "ok" if count else "empty"
            cols[s] = (count, status)
            save_coverage(conn, run_id, "apifootball", label, lid, s, count, status)
        rows.append((label, cols))
        print(f"  {label:26} " + " ".join(
            f"{s}:{cell(*cols[s])}" for s in SEASONS))
    print_matrix("API-Football", rows, SEASONS)


def af_coverage_probe(session, conn, run_id):
    """Build the injury-coverage map from the single /leagues call — reads each
    league's per-season `coverage.injuries` flag. Costs ONE request total, no
    per-league injury calls, so it is quota-cheap and authoritative.
    """
    _af_state["provider"] = "apifootball"
    _af_state["log"] = make_log_path("apifootball", run_id)
    print(f"  logging responses -> {_af_state['log']}")
    resolved = af_resolve_leagues(session, conn)
    print("  reading coverage.injuries flags (no per-league injury calls) …")

    rows = []
    covered = []
    for label, country, _hint in TARGETS:
        item = resolved.get(label)
        cols = {}
        if item is None:
            for s in SEASONS:
                cols[s] = (None, "unresolved")
                save_coverage(conn, run_id, "apifootball", label, None, s, None,
                              "coverage:unresolved")
            rows.append((label, cols))
            continue
        lid = item["league"]["id"]
        by_year = {se.get("year"): se for se in item.get("seasons", [])}
        any_cov = False
        for s in SEASONS:
            se = by_year.get(s)
            if se is None:
                cols[s] = (None, "no_season")
                save_coverage(conn, run_id, "apifootball", label, lid, s, None,
                              "coverage:no_season")
                continue
            flag = bool((se.get("coverage") or {}).get("injuries"))
            any_cov = any_cov or flag
            cols[s] = (1 if flag else 0, "ok" if flag else "empty")
            save_coverage(conn, run_id, "apifootball", label, lid, s,
                          1 if flag else 0, "coverage:yes" if flag else "coverage:no")
        rows.append((label, cols))
        if any_cov:
            covered.append(label)
    # Render as YES/·/— rather than counts for a coverage view.
    print("\n### API-Football — injury COVERAGE map (from coverage.injuries flag)\n")
    label_w = max(len("League"), max(len(r[0]) for r in rows))
    cols_hdr = [str(s) for s in SEASONS]
    print("| " + "League".ljust(label_w) + " | " + " | ".join(cols_hdr) + " |")
    print("|" + "-" * (label_w + 2) + "|" + "|".join("-" * (len(c) + 2) for c in cols_hdr) + "|")
    for label, cols in rows:
        cells = []
        for s in SEASONS:
            _, status = cols[s]
            mark = {"ok": "YES", "empty": "·", "no_season": "n/a",
                    "unresolved": "—"}.get(status, status)
            cells.append(mark.ljust(len(str(s))))
        print("| " + label.ljust(label_w) + " | " + " | ".join(cells) + " |")
    print(f"\nLegend: YES = has injury coverage · `·` = no coverage · "
          f"`n/a` = season not in API · `—` = league not resolved\n")
    print(f"COVERED ({len(covered)}/{len(TARGETS)}): "
          + (", ".join(covered) if covered else "none"))
    print("\nThis map is API-Football's own coverage flag; confirm a couple of "
          "YES leagues with an actual count run (--mode counts) before trusting.\n")


# --------------------------------------------------------------------------- #
# Sportmonks
# --------------------------------------------------------------------------- #
SM_BASE = "https://api.sportmonks.com/v3/football"
# In-season sample window (European leagues are mid-season here). Used to
# sample the `sidelined` include; historical-by-season is deferred for v0.1.
SM_WINDOW = ("2026-02-01", "2026-03-01")
# Sportmonks free tier allows a generous hourly quota; light pacing is enough.
SM_MIN_INTERVAL = 0.8
_sm_state = {"last": 0.0}


def sm_get(session, token, path, params=None):
    p = {"api_token": token}
    p.update(params or {})
    return polite_get(session, f"{SM_BASE}{path}", p, SM_MIN_INTERVAL, _sm_state)


def sm_report_quota(r):
    """Print Sportmonks hourly quota from the response's meta.rate_limit block."""
    try:
        rl = (r.json().get("rate_limit") or {})
        if rl:
            print(f"  quota: {rl.get('remaining')} requests left this hour "
                  f"(resets in {rl.get('resets_in_seconds')}s)")
    except ValueError:
        pass


def sm_list_accessible(session, token):
    """Diagnostic: list the leagues actually exposed by the current plan.

    On the free tier this is expected to be just Danish Superliga + Scottish
    Premiership — which explains why our target searches return nothing.
    """
    r = sm_get(session, token, "/leagues", {"include": "country", "per_page": "100"})
    if r.status_code != 200:
        print(f"  (plan check: /leagues HTTP {r.status_code})")
        return
    data = r.json().get("data", [])
    print(f"  plan exposes {len(data)} league(s):")
    for it in data[:50]:
        country = (it.get("country") or {}).get("name", "?")
        print(f"    - {it.get('name')} ({country}) [id {it.get('id')}]")


def sm_resolve_leagues(session, token, conn):
    print("Sportmonks: resolving leagues …")
    sm_list_accessible(session, token)
    resolved = {}
    reported = False
    for label, country, hint in TARGETS:
        query = (hint or label).split(" (")[0]
        r = sm_get(session, token, f"/leagues/search/{requests.utils.quote(query)}",
                   {"include": "country"})  # paced internally
        if not reported and r.status_code == 200:
            sm_report_quota(r)
            reported = True
        if r.status_code != 200:
            save_league(conn, "sportmonks", label, country, None, None, False)
            print(f"  ✗ {label:26} -> search HTTP {r.status_code}")
            continue
        data = r.json().get("data", [])
        chosen = None
        for it in data:
            c = (it.get("country") or {}).get("name", "")
            if c and c.lower().replace("-", " ") == country.lower().replace("-", " "):
                chosen = it
                break
        # No country fallback: a name-only match (e.g. Scotland "Premiership"
        # matching a "Premier" hint) would misattribute another league's data.
        if chosen:
            lid = chosen["id"]
            lname = chosen.get("name")
            resolved[label] = lid
            save_league(conn, "sportmonks", label, country, lid, lname, True)
            print(f"  ✓ {label:26} -> id {lid} ({lname})")
        else:
            save_league(conn, "sportmonks", label, country, None, None, False)
            print(f"  ✗ {label:26} -> no match for '{query}'")
    return resolved


def sm_probe(session, token, conn, run_id):
    _sm_state["provider"] = "sportmonks"
    _sm_state["log"] = make_log_path("sportmonks", run_id)
    print(f"  logging responses -> {_sm_state['log']}")
    resolved = sm_resolve_leagues(session, token, conn)
    col = "current (sampled)"
    rows = []
    for label, country, _hint in TARGETS:
        lid = resolved.get(label)
        if lid is None:
            rows.append((label, {col: (None, "unresolved")}))
            save_coverage(conn, run_id, "sportmonks", label, None, col, None, "unresolved")
            continue
        d1, d2 = SM_WINDOW
        # Paginate: a busy league/window can exceed the default page size and
        # silently truncate otherwise (found and fixed the same bug in
        # sm_sweep55.py — a single-page call risks under-counting exactly the
        # leagues with the most fixtures, i.e. the ones that matter most).
        fixtures, page, last_status, last_text = [], 1, 200, ""
        while page <= 5:
            r = sm_get(session, token, f"/fixtures/between/{d1}/{d2}",
                       {"filters": f"fixtureLeagues:{lid}", "include": "sidelined",
                        "per_page": "100", "page": str(page)})
            last_status, last_text = r.status_code, r.text
            if r.status_code != 200:
                break
            body = r.json()
            batch = body.get("data", [])
            fixtures.extend(batch)
            pag = body.get("pagination") or {}
            if not batch or not pag.get("has_more"):
                break
            page += 1
        if last_status in (401, 403):
            rows.append((label, {col: (None, "not_in_plan")}))
            save_coverage(conn, run_id, "sportmonks", label, lid, col, None,
                          "not_in_plan", f"HTTP {last_status}")
            print(f"  {label:26} plan✗ (HTTP {last_status})")
            continue
        if last_status != 200:
            rows.append((label, {col: (None, "error")}))
            save_coverage(conn, run_id, "sportmonks", label, lid, col, None,
                          "error", f"HTTP {last_status}: {last_text[:120]}")
            print(f"  {label:26} ERR (HTTP {last_status})")
            continue
        sidelined = sum(len(f.get("sidelined", []) or []) for f in fixtures)
        status = "ok" if sidelined else "empty"
        rows.append((label, {col: (sidelined, status)}))
        save_coverage(conn, run_id, "sportmonks", label, lid, col, sidelined, status,
                      f"{len(fixtures)} fixtures in window")
        print(f"  {label:26} {cell(sidelined, status)} "
              f"({len(fixtures)} fixtures sampled)")
    print_matrix("Sportmonks", rows, [col])
    print("Note: Sportmonks column is a SAMPLE of the `sidelined` include over "
          f"{SM_WINDOW[0]}..{SM_WINDOW[1]}, not a full-season count. "
          "Historical-by-season is deferred to a later iteration.\n")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Injury-data coverage probe (v0.1)")
    ap.add_argument("--provider", choices=["apifootball", "sportmonks", "both"],
                    default="both")
    ap.add_argument("--targets", choices=["sample", "uefa55"], default="sample",
                    help="sample = Big 5 + 5 small (default); uefa55 = all 55 "
                         "UEFA top-tier leagues")
    ap.add_argument("--seasons", default=None,
                    help="comma-separated season start years, e.g. '2024' or "
                         "'2023,2024'. Defaults to 2023,2024,2025.")
    ap.add_argument("--pace", type=float, default=None,
                    help="seconds between API-Football calls. Default 7.0 suits "
                         "the FREE tier (~10 req/min). On a paid plan (300+/min) "
                         "use --pace 1 to run ~7x faster.")
    ap.add_argument("--mode", choices=["coverage", "counts"], default=None,
                    help="coverage = read API-Football's coverage.injuries flag "
                         "in ONE call (cheap, authoritative map); counts = call "
                         "the injuries endpoint per league (spends quota). "
                         "Defaults to coverage for uefa55, counts for sample.")
    args = ap.parse_args()

    global TARGETS, SEASONS, AF_MIN_INTERVAL
    if args.pace is not None:
        AF_MIN_INTERVAL = args.pace
    TARGETS = UEFA55_TARGETS if args.targets == "uefa55" else SAMPLE_TARGETS
    if args.seasons:
        SEASONS = [int(x.strip()) for x in args.seasons.split(",") if x.strip()]
    elif args.targets == "uefa55":
        SEASONS = [2023, 2024, 2025]  # coverage flag is free, so span seasons
    mode = args.mode or ("coverage" if args.targets == "uefa55" else "counts")
    print(f"targets={args.targets} ({len(TARGETS)} leagues) · seasons={SEASONS} "
          f"· mode={mode}")

    conn = init_db()

    if args.provider in ("apifootball", "both"):
        key = os.getenv("APIFOOTBALL_KEY")
        if not key or key.startswith("REPLACE_"):
            print("! APIFOOTBALL_KEY not set in .env — skipping API-Football.")
        else:
            s = requests.Session()
            s.headers.update({"x-apisports-key": key})
            run_id = start_run(conn, "apifootball", f"seasons={SEASONS} mode={mode}")
            if mode == "coverage":
                af_coverage_probe(s, conn, run_id)
            else:
                af_probe(s, conn, run_id)

    if args.provider in ("sportmonks", "both"):
        token = os.getenv("SPORTMONKS_TOKEN") or os.getenv("SPORTMONKS_KEY")
        if not token or token.startswith("REPLACE_"):
            print("! SPORTMONKS token not set in .env — skipping Sportmonks.")
        else:
            s = requests.Session()
            run_id = start_run(conn, "sportmonks", f"window={SM_WINDOW}")
            sm_probe(s, token, conn, run_id)

    print(f"Results stored in {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
