"""Unit tests for the ingestion pipeline's pure/offline logic.

No live API here — that would burn real quota. We cover the parts that can be
tested without the network: month arithmetic, the pagination follower (with a
stubbed transport), watermark advancement, and sync's window computation.
"""
import time

from ingest.core import months
from ingest.sportmonks import backfill, enrich, sync
from ingest.sportmonks.backfill import RICH_FIXTURE_INCLUDE
from ingest.sportmonks.client import FIXTURE, SportmonksClient


# --------------------------------------------------------------------------- #
# Month arithmetic.
# --------------------------------------------------------------------------- #
def test_windows_between_is_inclusive_and_crosses_year():
    assert months.windows_between("2024-11", "2025-01") == [
        ("2024-11-01", "2024-12-01"),
        ("2024-12-01", "2025-01-01"),
        ("2025-01-01", "2025-02-01"),
    ]


def test_windows_between_empty_when_start_after_end():
    assert months.windows_between("2025-01", "2024-01") == []


def test_recent_windows_counts_back_from_end():
    assert months.recent_windows(3, end_ym="2025-02") == [
        ("2024-12-01", "2025-01-01"),
        ("2025-01-01", "2025-02-01"),
        ("2025-02-01", "2025-03-01"),
    ]


def test_next_ym_rolls_over_december():
    assert months.next_ym("2024-12") == "2025-01"
    assert months.next_ym("2024-03") == "2024-04"


# --------------------------------------------------------------------------- #
# Pagination follower — client.get is stubbed, so no network.
# --------------------------------------------------------------------------- #
def test_get_all_follows_has_more():
    client = SportmonksClient("token")
    pages = {
        1: (200, {"data": [1, 2], "pagination": {"has_more": True}}),
        2: (200, {"data": [3], "pagination": {"has_more": False}}),
    }
    seen = []
    client.get = lambda url, params=None: (seen.append(params["page"]), pages[params["page"]])[1]

    status, items, truncated, first = client.get_all("http://x")
    assert status == 200
    assert items == [1, 2, 3]
    assert truncated is False
    assert seen == [1, 2]


def test_get_all_flags_truncation_at_max_pages():
    client = SportmonksClient("token")
    client.get = lambda url, params=None: (200, {"data": [1], "pagination": {"has_more": True}})

    status, items, truncated, first = client.get_all("http://x", max_pages=3)
    assert truncated is True
    assert len(items) == 3


def test_get_all_stops_on_non_200():
    client = SportmonksClient("token")
    client.get = lambda url, params=None: (503, None)

    status, items, truncated, first = client.get_all("http://x")
    assert status == 503
    assert items == []
    assert truncated is False


# --------------------------------------------------------------------------- #
# Watermark advancement — forward-only, ignores misses.
# --------------------------------------------------------------------------- #
def test_advance_watermark_moves_forward_only():
    watermark = {}
    backfill.advance_watermark(watermark, 10, "2024-03")
    assert watermark["10"] == "2024-03"
    backfill.advance_watermark(watermark, 10, "2024-01")  # older — ignored
    assert watermark["10"] == "2024-03"
    backfill.advance_watermark(watermark, 10, "2024-05")  # newer — advances
    assert watermark["10"] == "2024-05"
    backfill.advance_watermark(watermark, 10, None)  # no data fetched — ignored
    assert watermark["10"] == "2024-05"


# --------------------------------------------------------------------------- #
# Sync window computation from the watermark.
# --------------------------------------------------------------------------- #
def test_windows_since_watermark_resumes_after_mark():
    assert sync.windows_since_watermark({"10": "2024-03"}, 10, until_ym="2024-05") == [
        ("2024-04-01", "2024-05-01"),
        ("2024-05-01", "2024-06-01"),
    ]


def test_windows_since_watermark_defaults_to_current_month_when_unseen():
    assert sync.windows_since_watermark({}, 99, until_ym="2024-05") == [
        ("2024-05-01", "2024-06-01"),
    ]


def test_windows_since_watermark_empty_when_up_to_date():
    assert sync.windows_since_watermark({"10": "2024-05"}, 10, until_ym="2024-05") == []


# --------------------------------------------------------------------------- #
# Proactive per-entity throttle — time.sleep stubbed so nothing actually waits.
# --------------------------------------------------------------------------- #
def _seed_quota(client, entity, remaining, resets_in_seconds, age_seconds=0):
    client._quota[entity.lower()] = {
        "remaining": remaining,
        "resets_in_seconds": resets_in_seconds,
        "observed_at": time.monotonic() - age_seconds,
    }


def test_await_quota_no_wait_when_entity_unseen():
    client = SportmonksClient("token")
    assert client.await_quota(FIXTURE) == 0.0


def test_await_quota_no_wait_when_quota_healthy():
    client = SportmonksClient("token")
    _seed_quota(client, FIXTURE, remaining=2999, resets_in_seconds=3600)
    assert client.await_quota(FIXTURE) == 0.0


def test_await_quota_no_wait_when_window_already_reset():
    client = SportmonksClient("token")
    # Exhausted, but observed long enough ago that the window has elapsed.
    _seed_quota(client, FIXTURE, remaining=0, resets_in_seconds=10, age_seconds=30)
    assert client.await_quota(FIXTURE) == 0.0


def test_await_quota_sleeps_until_reset_when_exhausted(monkeypatch):
    client = SportmonksClient("token")
    _seed_quota(client, FIXTURE, remaining=0, resets_in_seconds=3600)
    slept = []
    # String target: no import checker catches this one when the module moves.
    monkeypatch.setattr("ingest.sportmonks.client.time.sleep", slept.append)

    waited = client.await_quota(FIXTURE)
    assert waited > 3600 and slept and slept[0] == waited  # ~reset + buffer, no real delay

    # Case-insensitive: the lowercase spelling resolves to the same bucket and
    # still triggers a wait (value differs by a hair as the clock advances).
    assert client.await_quota("fixture") > 3600


# --------------------------------------------------------------------------- #
# Enrichment resumability predicates.
# --------------------------------------------------------------------------- #
def test_needs_player_enrich_keys_on_presence_not_truthiness():
    assert enrich.needs_player_enrich({"name": "x"}) is True          # never requested
    assert enrich.needs_player_enrich({}) is True
    assert enrich.needs_player_enrich({"statistics": []}) is False     # requested, empty career
    assert enrich.needs_player_enrich({"statistics": [{"season_id": 1}]}) is False


def test_needs_fixture_enrich_skips_empty_and_already_rich():
    thin = {"fixtures": [{"id": 1}], "include": "sidelined.sideline"}
    rich = {"fixtures": [{"id": 1}], "include": RICH_FIXTURE_INCLUDE}
    old_thin = {"fixtures": [{"id": 1}]}  # pre-enrichment file, no include recorded
    assert enrich.needs_fixture_enrich(thin) is True
    assert enrich.needs_fixture_enrich(old_thin) is True
    assert enrich.needs_fixture_enrich(rich) is False                  # already has lineups
    assert enrich.needs_fixture_enrich({"fixtures": []}) is False      # empty month, nothing to add
    assert enrich.needs_fixture_enrich({}) is False
