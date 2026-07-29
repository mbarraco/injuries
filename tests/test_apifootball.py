"""Unit tests for the API-Football client's pure/offline logic.

No live API here — that would burn real quota. We cover what can be tested
without the network: outcome classification, the pagination follower (with a
stubbed transport), quota bookkeeping from headers, pacing arithmetic, and the
coverage work-list flattening.

The classification tests carry the most weight. API-Football reports plan
gating, auth failure and quota exhaustion inside an HTTP 200 body, so code that
trusts the status line reads a plan wall as "this league has no data" — a wrong
answer that looks exactly like a right one.
"""
import json
import os
import tempfile

from ingest.apifootball import injuries, paths
from ingest.apifootball.client import (
    AUTH_FAILED, EMPTY, ERROR, OK, PLAN_BLOCKED, QUOTA_EXHAUSTED,
    ApiFootballClient, classify)
from ingest.core.cache import read_cache, write_cache


# --------------------------------------------------------------------------- #
# Outcome classification — a 200 is not a success.
# --------------------------------------------------------------------------- #
def test_classify_ok_when_results_present():
    body = {"errors": [], "results": 12, "response": [{"x": 1}]}
    assert classify(200, body) == (OK, "")


def test_classify_empty_is_a_real_answer_not_a_failure():
    # Verified against Belgium 2024 on 2026-07-23: clean 200, no errors,
    # results 0 -- the vendor genuinely has no data. Must stay distinct from
    # PLAN_BLOCKED or we would re-fetch it forever / call it a failure.
    outcome, _detail = classify(200, {"errors": [], "results": 0, "response": []})
    assert outcome == EMPTY


def test_classify_detects_plan_gating_inside_a_200():
    body = {"errors": {"plan": "Your plan does not grant access to this season"},
            "results": 0, "response": []}
    outcome, detail = classify(200, body)
    assert outcome == PLAN_BLOCKED
    assert "plan" in detail.lower()


def test_classify_detects_auth_failure_inside_a_200():
    body = {"errors": {"token": "invalid api key"}, "results": 0}
    assert classify(200, body)[0] == AUTH_FAILED


def test_classify_detects_quota_exhaustion_inside_a_200():
    body = {"errors": {"requests": "You have reached the request limit for the day"},
            "results": 0}
    assert classify(200, body)[0] == QUOTA_EXHAUSTED


def test_classify_maps_status_codes():
    assert classify(429, None)[0] == QUOTA_EXHAUSTED
    assert classify(401, None)[0] == AUTH_FAILED
    assert classify(403, None)[0] == AUTH_FAILED
    assert classify(503, None)[0] == ERROR
    assert classify(None, None)[0] == ERROR


def test_classify_treats_empty_error_containers_as_healthy():
    # Both [] and {} are seen in the wild for "no problem"; emptiness is the
    # test, not the container type.
    assert classify(200, {"errors": [], "results": 1})[0] == OK
    assert classify(200, {"errors": {}, "results": 1})[0] == OK


# --------------------------------------------------------------------------- #
# Pagination — client.get is stubbed, so no network.
# --------------------------------------------------------------------------- #
def _client():
    return ApiFootballClient("key")


def test_get_all_follows_paging_total():
    client = _client()
    pages = {
        1: (200, {"errors": [], "results": 2, "response": [1, 2],
                  "paging": {"current": 1, "total": 2}}, OK, ""),
        2: (200, {"errors": [], "results": 1, "response": [3],
                  "paging": {"current": 2, "total": 2}}, OK, ""),
    }
    seen = []
    # `page` is absent on the first request by design — default to 1 here.
    client.get = lambda path, params=None: (seen.append((params or {}).get("page", 1)),
                                            pages[(params or {}).get("page", 1)])[1]

    items, outcome, _detail, truncated = client.get_all("/injuries")
    assert items == [1, 2, 3]
    assert outcome == OK
    assert truncated is False
    assert seen == [1, 2]


def test_get_all_single_page_does_not_request_a_second():
    client = _client()
    seen = []
    client.get = lambda path, params=None: (
        seen.append((params or {}).get("page", 1)),
        (200, {"errors": [], "results": 1, "response": [1],
               "paging": {"current": 1, "total": 1}}, OK, ""))[1]

    items, outcome, _detail, _truncated = client.get_all("/injuries")
    assert items == [1] and outcome == OK and seen == [1]


def test_get_all_omits_page_on_the_first_request():
    """`/injuries` rejects the field outright: HTTP 200 with
    errors={"page": "The Page field do not exist."} and zero records. Sending
    it only from page 2 keeps non-paginating endpoints working. Measured
    2026-07-29; cost 5 wasted calls to diagnose, hence the explicit test."""
    client = _client()
    seen = []
    client.get = lambda path, params=None: (
        seen.append(dict(params or {})),
        (200, {"errors": [], "results": 1, "response": [1],
               "paging": {"current": 1, "total": 2}}, OK, ""))[1]

    client.get_all("/injuries", {"league": 39, "season": 2024}, max_pages=2)
    assert "page" not in seen[0]                      # first request is clean
    assert seen[0] == {"league": 39, "season": 2024}  # and carries nothing else
    assert seen[1]["page"] == 2                       # later pages are explicit


def test_get_all_flags_truncation_at_max_pages():
    client = _client()
    client.get = lambda path, params=None: (
        200, {"errors": [], "results": 1, "response": [1],
              "paging": {"current": 1, "total": 99}}, OK, "")

    items, _outcome, _detail, truncated = client.get_all("/injuries", max_pages=3)
    assert truncated is True
    assert len(items) == 3


def test_get_all_keeps_pages_already_paid_for_on_mid_run_failure():
    client = _client()
    pages = {
        1: (200, {"errors": [], "results": 1, "response": [1],
                  "paging": {"current": 1, "total": 3}}, OK, ""),
        2: (200, None, PLAN_BLOCKED, "plan"),
    }
    client.get = lambda path, params=None: pages[(params or {}).get("page", 1)]

    items, outcome, _detail, _truncated = client.get_all("/injuries")
    assert items == [1]              # page 1 not discarded
    assert outcome == PLAN_BLOCKED   # but the failure is surfaced, not hidden


def test_get_all_reports_empty_when_no_items_anywhere():
    client = _client()
    client.get = lambda path, params=None: (
        200, {"errors": [], "results": 0, "response": [],
              "paging": {"current": 1, "total": 1}}, EMPTY, "results=0")

    items, outcome, _detail, _truncated = client.get_all("/injuries")
    assert items == [] and outcome == EMPTY


# --------------------------------------------------------------------------- #
# Quota bookkeeping from response headers.
# --------------------------------------------------------------------------- #
def test_record_quota_reads_both_windows():
    client = _client()
    client._record_quota({
        "x-ratelimit-requests-remaining": "7490",
        "x-ratelimit-requests-limit": "7500",
        "X-RateLimit-Remaining": "295",
        "X-RateLimit-Limit": "300",
    })
    snapshot = client.quota()
    assert snapshot["day_remaining"] == 7490
    assert snapshot["day_limit"] == 7500
    assert snapshot["minute_remaining"] == 295
    assert snapshot["minute_limit"] == 300


def test_observed_minute_limit_corrects_a_wrong_seed():
    # Seeded for the free tier; one Pro response should widen the pacer.
    client = ApiFootballClient("key", minute_limit=10)
    before = client.min_interval
    client._record_quota({"X-RateLimit-Limit": "300", "X-RateLimit-Remaining": "299"})
    assert client.min_interval < before


def test_record_quota_ignores_missing_and_malformed_headers():
    client = _client()
    client._record_quota({"X-RateLimit-Remaining": "not-a-number"})
    client._record_quota(None)
    assert client.quota()["minute_remaining"] is None


# --------------------------------------------------------------------------- #
# Daily budget guard.
# --------------------------------------------------------------------------- #
def test_can_afford_is_permissive_before_anything_is_observed():
    # Must never block a run on missing information -- it is a courtesy check.
    affordable, remaining = _client().can_afford(10_000)
    assert affordable is True and remaining is None


def test_can_afford_compares_against_observed_remaining():
    client = _client()
    client._record_quota({"x-ratelimit-requests-remaining": "100"})
    assert client.can_afford(100) == (True, 100)
    assert client.can_afford(101) == (False, 100)


# --------------------------------------------------------------------------- #
# Pacing arithmetic — no real sleeping.
# --------------------------------------------------------------------------- #
def test_min_interval_leaves_headroom_under_the_ceiling():
    client = ApiFootballClient("key", minute_limit=300)
    # 300/min would be 0.2s; safety margin must make it strictly slower.
    assert client.min_interval > 0.2
    assert 300 * client.min_interval > 60  # i.e. under 300 requests in a minute


def test_reserve_slot_hands_out_non_overlapping_slots(monkeypatch):
    client = ApiFootballClient("key", minute_limit=300)
    monkeypatch.setattr("ingest.apifootball.client.time.sleep", lambda _s: None)

    first = client._next_slot
    client._reserve_slot()
    second = client._next_slot
    client._reserve_slot()
    third = client._next_slot

    # Each reservation pushes the clock forward by at least one interval, so
    # concurrent workers cannot claim the same instant and burst past the cap.
    assert second > first
    assert third - second >= client.min_interval * 0.999


# --------------------------------------------------------------------------- #
# Coverage work list.
# --------------------------------------------------------------------------- #
def test_covered_league_seasons_flattens_to_one_row_per_pair():
    coverage = {"leagues": [
        {"country": "England", "league": "Premier League", "id": 39,
         "injury_seasons": [2023, 2024]},
        {"country": "Malta", "league": "Premier League", "id": 393,
         "injury_seasons": []},
    ]}
    assert paths.covered_league_seasons(coverage) == [
        (39, 2023, "England", "Premier League"),
        (39, 2024, "England", "Premier League"),
    ]


def test_load_coverage_raises_with_a_recovery_hint_when_absent(monkeypatch):
    monkeypatch.setattr(paths, "COVERAGE_FILE", "/nonexistent/coverage.json")
    try:
        paths.load_coverage()
    except FileNotFoundError as error:
        assert "af_status_and_coverage" in str(error)  # tells you how to fix it
    else:
        raise AssertionError("expected FileNotFoundError")


# --------------------------------------------------------------------------- #
# Injuries runner — what gets cached, and what must not.
# --------------------------------------------------------------------------- #
class _StubClient:
    """Stands in for ApiFootballClient.get_all with a scripted outcome."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def get_all(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return self.result


def _in_temp_cache(monkeypatch, directory):
    monkeypatch.setattr(paths, "INJURIES_DIR", directory)


def test_fetch_caches_records_on_success(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        _in_temp_cache(monkeypatch, directory)
        client = _StubClient(([{"player": "a"}, {"player": "b"}], OK, "", False))

        count, outcome, _detail, from_cache = injuries.fetch_league_season(
            client, 39, 2024)
        assert (count, outcome, from_cache) == (2, OK, False)

        written = read_cache(os.path.join(directory, "39_2024.json"))
        assert written["league_id"] == 39 and written["season"] == 2024
        assert len(written["injuries"]) == 2


def test_fetch_caches_a_genuine_empty_so_it_is_never_re_paid_for(monkeypatch):
    # EMPTY is a real answer about the DATA. Not caching it would make every
    # future run re-buy the same "there is nothing here".
    with tempfile.TemporaryDirectory() as directory:
        _in_temp_cache(monkeypatch, directory)
        client = _StubClient(([], EMPTY, "results=0", False))

        count, outcome, _detail, _cached = injuries.fetch_league_season(
            client, 393, 2025)
        assert (count, outcome) == (0, EMPTY)
        assert read_cache(os.path.join(directory, "393_2025.json")) is not None


def test_fetch_does_not_cache_access_failures(monkeypatch):
    # PLAN_BLOCKED / AUTH / QUOTA describe OUR ACCESS, not the data. Caching one
    # would freeze a temporary condition into the permanent record and hide the
    # gap from every later run.
    for outcome in (PLAN_BLOCKED, AUTH_FAILED, QUOTA_EXHAUSTED, ERROR):
        with tempfile.TemporaryDirectory() as directory:
            _in_temp_cache(monkeypatch, directory)
            client = _StubClient(([], outcome, "blocked", False))

            count, seen, _detail, _cached = injuries.fetch_league_season(
                client, 39, 2024)
            assert count is None and seen == outcome
            assert read_cache(os.path.join(directory, "39_2024.json")) is None


def test_fetch_is_cache_first_and_skips_the_network(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        _in_temp_cache(monkeypatch, directory)
        write_cache(os.path.join(directory, "39_2024.json"),
                    {"league_id": 39, "season": 2024, "outcome": OK,
                     "injuries": [{"player": "a"}]})
        client = _StubClient(([], ERROR, "should not be called", False))

        count, outcome, _detail, from_cache = injuries.fetch_league_season(
            client, 39, 2024)
        assert (count, outcome, from_cache) == (1, OK, True)
        assert client.calls == []   # network never touched


def test_refresh_bypasses_the_cache(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        _in_temp_cache(monkeypatch, directory)
        write_cache(os.path.join(directory, "39_2024.json"),
                    {"league_id": 39, "season": 2024, "outcome": OK, "injuries": []})
        client = _StubClient(([{"player": "new"}], OK, "", False))

        count, _outcome, _detail, from_cache = injuries.fetch_league_season(
            client, 39, 2024, refresh=True)
        assert (count, from_cache) == (1, False)
        assert client.calls  # network WAS used


def test_fetch_queries_by_league_and_season():
    client = _StubClient(([], EMPTY, "", False))
    with tempfile.TemporaryDirectory() as directory:
        original = paths.INJURIES_DIR
        try:
            paths.INJURIES_DIR = directory
            injuries.fetch_league_season(client, 140, 2023)
        finally:
            paths.INJURIES_DIR = original
    assert client.calls == [("/injuries", {"league": 140, "season": 2023})]


def test_load_coverage_reads_a_real_file():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "coverage.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"leagues": [{"id": 1, "injury_seasons": [2024]}]}, handle)
        # Read through the module constant so the production path is exercised.
        original = paths.COVERAGE_FILE
        try:
            paths.COVERAGE_FILE = path
            assert paths.load_coverage()["leagues"][0]["id"] == 1
        finally:
            paths.COVERAGE_FILE = original
