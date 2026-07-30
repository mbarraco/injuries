"""Tests for the API-Football transfer layer.

Split by what can fail silently:

* `classify_transfer_type` — a mis-parsed fee or an unrecognised category word
  produces a plausible wrong number, never an error. Every case here comes from
  a value actually measured in the 2026-07-30 probe.
* The query layer — dedup, id-less club sides, and the "N of M" contract.
* The schema's own invariant view, `af_unmapped_transfer_type`.
"""
import sqlite3

import pytest

from app import af_queries, etl_af
from app import db as db_module


# --------------------------------------------------------------------------- #
# Fee parsing. `type` is a three-way mixed field: category word, fee, or
# null-marker. All the strings below were observed in the probe.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,amount,currency,fee_eur,fee_format", [
    # "sym_num" — the dominant format (281 of 289 sampled fee rows).
    ("€ 7M",     7_000_000, "EUR", 7_000_000, "sym_num"),
    ("€ 800K",     800_000, "EUR",   800_000, "sym_num"),
    ("€ 248.5K",   248_500, "EUR",   248_500, "sym_num"),
    # No space after the symbol. Same format, different spacing.
    ("€7M",      7_000_000, "EUR", 7_000_000, "sym_num"),
    # "num_sym" — symbol trails the value.
    ("1.5M €",   1_500_000, "EUR", 1_500_000, "num_sym"),
    ("3M €",     3_000_000, "EUR", 3_000_000, "num_sym"),
    # "bare" — an amount with NO currency symbol at all. The amount is known
    # and the denomination is not, so fee_eur must stay None. Treating this as
    # euros would be a guess presented as a measurement.
    ("2.6M",     2_600_000,  None,      None, "bare"),
])
def test_fee_strings_parse_with_their_format_recorded(
        raw, amount, currency, fee_eur, fee_format):
    category, got_amount, got_currency, got_eur, got_format = \
        etl_af.classify_transfer_type(raw)
    assert category == "fee"
    assert got_amount == amount
    assert got_currency == currency
    assert got_eur == fee_eur
    assert got_format == fee_format


@pytest.mark.parametrize("raw,amount,currency", [
    # The vendor HTML-escapes pound signs. Left escaped, every one of these
    # matched neither a category nor the fee pattern and was filed as 'unknown',
    # so ~20 real fees disappeared from every total without an error.
    ("&pound; 7M",     7_000_000, "GBP"),
    ("&pound; 15M",   15_000_000, "GBP"),
    ("&pound; 2.7M",   2_700_000, "GBP"),
    ("450K &pound;",     450_000, "GBP"),
])
def test_html_escaped_currency_symbols_are_decoded(raw, amount, currency):
    category, got_amount, got_currency, fee_eur, _fmt = \
        etl_af.classify_transfer_type(raw)
    assert (category, got_amount, got_currency) == ("fee", amount, currency)
    # Still not euros, so still excluded from any euro total.
    assert fee_eur is None


def test_escaped_pound_na_is_unknown_not_a_fee():
    """"&pound; N/A" is a currency symbol on a null-marker, not an amount."""
    assert etl_af.classify_transfer_type("&pound; N/A")[0] == "unknown"


def test_non_euro_fee_parses_an_amount_but_never_a_euro_value():
    """The guard against an undetectable error.

    Only euros appeared in the probe, but the sample was two European clubs. A
    dollar fee silently summed into a euro total is invisible — so a non-euro
    symbol yields fee_amount and fee_currency, and fee_eur stays None.
    """
    category, amount, currency, fee_eur, _fmt = \
        etl_af.classify_transfer_type("$ 10M")
    assert (category, amount, currency) == ("fee", 10_000_000, "USD")
    assert fee_eur is None


@pytest.mark.parametrize("raw,expected", [
    ("Loan", "loan"),
    # Three vendor spellings of one concept — all must collapse together.
    ("Return from loan", "loan_return"),
    ("Back from Loan", "loan_return"),
    ("End of Loan", "loan_return"),
    ("Free", "free"),
    ("Free Transfer", "free"),
    # NOT folded into 'free': a signing made while unattached is a different
    # fact about the player than a fee-free move between two clubs.
    ("Free agent", "free_agent"),
    # A paid move with an undisclosed fee is NOT the same as "no information".
    ("Transfer", "undisclosed"),
    ("Swap", "swap"),
    # The vendor's own null-markers.
    ("N/A", "unknown"),
    ("-", "unknown"),
    ("", "unknown"),
    # Meaning undetermined — left unknown rather than guessed.
    ("Raise", "unknown"),
    # Found only in the full 313k-row build, never in the probe sample.
    ("End of career", "career_end"),   # retirement, not a club move
    ("Player Swap", "swap"),
    ("Trial", "trial"),
    # A currency symbol glued to a category word. "€ Free" is 187 rows and
    # means free; parsed naively it is neither a category nor a fee, so it was
    # landing in 'unknown' and inflating the unknown share.
    ("€ Free", "free"),
    ("Free €", "free"),
    ("€ N/A", "unknown"),
    ("$ N/A", "unknown"),
])
def test_category_words_classify_without_being_mistaken_for_fees(raw, expected):
    category, amount, _currency, fee_eur, fee_format = \
        etl_af.classify_transfer_type(raw)
    assert category == expected
    assert amount is None and fee_eur is None and fee_format is None


def test_free_agent_is_not_collapsed_into_free():
    """Regression guard for the tempting simplification.

    'Free' and 'Free agent' differ by 45 rows' worth of meaning in the sample:
    one is a move between two clubs for no fee, the other a signing of a player
    who had no club. Merging them loses the ability to ask either question.
    """
    assert etl_af.classify_transfer_type("Free")[0] != \
           etl_af.classify_transfer_type("Free agent")[0]


def test_undisclosed_fee_is_not_collapsed_into_unknown():
    """'Transfer' means money changed hands; 'N/A' means we don't know what
    happened. Same absence of a number, different facts."""
    assert etl_af.classify_transfer_type("Transfer")[0] != \
           etl_af.classify_transfer_type("N/A")[0]


def test_unrecognised_value_becomes_unknown_rather_than_vanishing():
    """The ETL must never drop a type it doesn't recognise: af_transfer_type is
    the join target, so a missing row removes the transfer from
    af_transfer_detail entirely instead of showing it as uncategorised."""
    category, amount, currency, fee_eur, fee_format = \
        etl_af.classify_transfer_type("Some Future Vendor Value")
    assert category == "unknown"
    assert (amount, currency, fee_eur, fee_format) == (None, None, None, None)


# --------------------------------------------------------------------------- #
# Dedup. Measured: the documented natural key collides on byte-identical rows,
# and a covered-club-to-covered-club move is reported three times over.
# --------------------------------------------------------------------------- #
def _cache_document(subject, subject_id, player_id, moves):
    return {"subject": subject, "subject_id": subject_id, "outcome": "ok",
            "paging_total": 1,
            "transfers": [{"player": {"id": player_id, "name": "Test Player"},
                           "update": "2026-07-30T00:00:00+00:00",
                           "transfers": moves}]}


def _move(date, type_, out_id, in_id, out_name="Out FC", in_name="In FC"):
    return {"date": date, "type": type_,
            "teams": {"out": {"id": out_id, "name": out_name},
                      "in": {"id": in_id, "name": in_name}}}


@pytest.fixture
def transfer_cache(tmp_path, monkeypatch):
    """A raw-cache tree shaped exactly like the real one, sharded included."""
    import json
    import os
    raw = tmp_path / "raw"
    monkeypatch.setattr(etl_af, "RAW", str(raw))

    def write(subject, subdir, subject_id, player_id, moves):
        shard = f"{subject_id % 100:02d}"
        directory = raw / subdir / shard
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{subject_id}.json").write_text(json.dumps(
            _cache_document(subject, subject_id, player_id, moves)))

    return write


def test_same_move_seen_from_both_subjects_collapses_to_one_row(transfer_cache):
    move = _move("2020-08-01", "€ 5M", 194, 645)
    transfer_cache("team", "transfers_team", 194, 19034, [move])
    transfer_cache("player", "transfers_player", 19034, 19034, [move])

    rows, type_counts, stats = etl_af.collect_transfers()
    assert stats["raw_rows"] == 2
    assert len(rows) == 1
    assert stats["collapsed"] == 1
    # Agreement is recorded, not discarded — that is the whole reason `source`
    # exists rather than being dropped by the dedup that relies on it.
    assert rows[0]["source"] == "both"
    assert stats["confirmed_by_club_and_player"] == 1


def test_true_vendor_duplicates_are_collapsed_and_counted_separately(transfer_cache):
    """A file listing the same move twice must collapse, and be counted as a
    duplicate rather than as corroboration.

    Measured over 464,657 real rows this case is currently ZERO — the probe's
    apparent duplicates were two clubs agreeing (see the test below). The
    counter and this test stay because "not observed yet" is not "cannot
    happen", and nothing else would notice if it started.
    """
    move = _move("2020-08-01", "N/A", 194, 645)
    transfer_cache("team", "transfers_team", 194, 19034, [move, dict(move)])

    rows, _types, stats = etl_af.collect_transfers()
    assert len(rows) == 1
    assert stats["duplicate_within_file"] == 1
    assert stats.get("confirmed_by_club_and_player", 0) == 0
    assert stats.get("corroborated_within_subject", 0) == 0
    assert rows[0]["source"] == "team"


def test_both_clubs_reporting_one_move_is_agreement_not_duplication(transfer_cache):
    """The case an earlier version got backwards, at a scale of ~97,000 rows.

    A move between two covered clubs appears in BOTH clubs' team files. Both
    carry subject "team", so comparing subject alone filed this as a
    byte-identical vendor duplicate — the opposite of what it is. Counting has
    to be per source FILE, not per subject type.
    """
    move = _move("2020-08-01", "€ 5M", 194, 645)
    transfer_cache("team", "transfers_team", 194, 19034, [move])   # selling club
    transfer_cache("team", "transfers_team", 645, 19034, [move])   # buying club

    rows, _types, stats = etl_af.collect_transfers()
    assert len(rows) == 1
    assert stats["collapsed"] == 1
    assert stats["corroborated_within_subject"] == 1
    # Two clubs agreeing is not a vendor duplicate...
    assert stats.get("duplicate_within_file", 0) == 0
    # ...and it is not club-and-player agreement either, so `source` stays
    # "team": no player file has confirmed this move.
    assert stats.get("confirmed_by_club_and_player", 0) == 0
    assert rows[0]["source"] == "team"


def test_distinct_moves_on_the_same_date_are_kept(transfer_cache):
    """Dedup must not over-collapse: two different moves can share a date, and
    July 1 stamping makes that common rather than exotic."""
    transfer_cache("player", "transfers_player", 500, 500, [
        _move("2021-07-01", "Loan", 100, 200),
        _move("2021-07-01", "Loan", 200, 300),
    ])
    rows, _types, stats = etl_af.collect_transfers()
    assert len(rows) == 2
    assert stats.get("collapsed", 0) == 0


def test_id_less_club_side_is_kept_and_counted(transfer_cache):
    """The vendor sometimes puts a PLAYER in the club field ("Icardi Mauro").
    The row is real and must be kept; the count exists so the app knows how
    many sides it has to render as plain text instead of a link."""
    transfer_cache("player", "transfers_player", 600, 600, [
        {"date": "2024-07-01", "type": "Free",
         "teams": {"out": {"id": None, "name": "Icardi Mauro"},
                   "in": {"id": 100, "name": "Real Club"}}},
    ])
    rows, _types, stats = etl_af.collect_transfers()
    assert len(rows) == 1
    assert rows[0]["from_team_id"] is None
    assert rows[0]["from_team_name"] == "Icardi Mauro"
    assert stats["sides_without_id"] == 1


def test_empty_cache_yields_no_rows_rather_than_failing(transfer_cache):
    """A build before the transfer crawl has run must still succeed."""
    rows, type_counts, stats = etl_af.collect_transfers()
    assert rows == [] and not type_counts
    assert stats["team_files"] == 0 and stats["player_files"] == 0


# --------------------------------------------------------------------------- #
# Query layer, against the `af_connection` fixture in conftest.py.
# --------------------------------------------------------------------------- #
def test_player_transfers_returns_the_real_total_beside_the_page(af_connection):
    result = af_queries.player_transfers(af_connection, 1, limit=2)
    assert result["total"] == 3          # player 1 has 3 moves
    assert result["shown"] == 2          # but only 2 are returned
    assert len(result["rows"]) == 2


def test_player_transfers_newest_first(af_connection):
    items = af_queries.player_transfers(af_connection, 1)["rows"]
    assert [row["date"] for row in items] == [
        "2019-07-01", "2019-01-15", "2016-07-01"]


def test_transfers_exist_for_a_player_with_no_af_player_row(af_connection):
    """Player 3 has no af_player row — most transfer subjects predate the
    2020–2025 window, so requiring a profile would discard the history that
    makes this table worth having."""
    assert af_queries.player_detail(af_connection, 3) is None
    result = af_queries.player_transfers(af_connection, 3)
    assert result["total"] == 1


def test_team_transfers_separate_incoming_from_outgoing(af_connection):
    result = af_queries.team_transfers(af_connection, 100)
    assert result["incoming"]["total"] == 5    # 5 moves TO team 100
    assert result["outgoing"]["total"] == 2    # 2 moves FROM team 100
    assert all(row["to_team_id"] == 100 for row in result["incoming"]["rows"])
    assert all(row["from_team_id"] == 100 for row in result["outgoing"]["rows"])


def test_linkable_flags_mark_the_id_less_side(af_connection):
    """Beta's 2024 move has a club side with a name and no id. The flag exists
    so a template cannot render it as a link by forgetting to check."""
    items = af_queries.player_transfers(af_connection, 2)["rows"]
    row = next(r for r in items if r["from_team_name"] == "Icardi Mauro")
    assert not row["from_linkable"]
    assert row["to_linkable"]


def test_transfer_categories_collapse_the_free_synonyms(af_connection):
    categories = {row["category"]: row["moves"]
                  for row in af_queries.transfer_categories(af_connection)}
    # 'Free' and 'Free Transfer' are two vendor strings, one category.
    assert categories["free"] == 2
    assert categories["loan"] == 2
    assert categories["fee"] == 2
    assert categories["unknown"] == 1


def test_fee_total_counts_only_rows_that_have_a_euro_fee(af_connection):
    """The bare '2.6M' row carries an amount with no stated currency, so it
    must NOT contribute to a euro total."""
    row = next(r for r in af_queries.transfer_categories(af_connection)
               if r["category"] == "fee")
    assert row["moves"] == 2         # '€ 7M' and '2.6M'
    assert row["fee_rows"] == 1      # only the euro one
    assert row["fee_eur_total"] == 7_000_000


def test_transfer_overview_states_the_span_and_the_caveats(af_connection):
    overview = af_queries.transfer_overview(af_connection)
    assert overview["moves"] == 7
    # Reaches before 2020, unlike every other table in this database.
    assert overview["earliest"] == "2016-07-01"
    assert overview["fee_rows"] == 1
    assert overview["confirmed_both"] == 1
    assert overview["unlinkable_sides"] == 1
    assert "season, not the day" in overview["date_note"]


def test_transfers_by_year_groups_on_the_calendar_year(af_connection):
    years = {row["year"]: row["moves"]
             for row in af_queries.transfers_by_year(af_connection)}
    assert years["2019"] == 2
    assert years["2016"] == 1


# --------------------------------------------------------------------------- #
# The schema's own invariant.
# --------------------------------------------------------------------------- #
def test_unmapped_transfer_type_view_is_empty_for_a_clean_build(af_connection):
    assert af_connection.execute(
        "SELECT COUNT(*) FROM af_unmapped_transfer_type").fetchone()[0] == 0


def test_unmapped_transfer_type_view_reports_a_missing_mapping(af_db_path):
    """The failure this view exists to catch. af_transfer_detail LEFT JOINs
    af_transfer_type, so a type with no row there would otherwise just quietly
    show a NULL category instead of announcing the gap."""
    writer = sqlite3.connect(af_db_path)
    writer.execute(
        "INSERT INTO af_transfer (player_id, player_name, date, type, "
        "from_team_id, to_team_id, source) "
        "VALUES (1, 'Alpha', '2025-07-01', 'Brand New Vendor Value', 100, 900, 'player')")
    writer.commit()
    writer.close()

    connection = db_module.connect_af(af_db_path)
    try:
        unmapped = connection.execute(
            "SELECT type, rows_affected FROM af_unmapped_transfer_type").fetchall()
        assert [tuple(row) for row in unmapped] == [("Brand New Vendor Value", 1)]
        # And the row is still present in the view rather than dropped — the
        # whole point of the LEFT JOIN.
        assert connection.execute(
            "SELECT COUNT(*) FROM af_transfer_detail").fetchone()[0] == 8
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# A database built BEFORE the transfer tables existed.
#
# This is not hypothetical. `app/apifootball.db` is a committed binary artifact,
# so code and database ship at different moments: the code went live while the
# deployed file was still a pre-transfer build, and every /af/player/{id} and
# /af/team/{id} page returned 500 with "no such table: af_transfer". Those pages
# are not about transfers and had worked for weeks — they broke because a new
# feature was wired into them as a hard dependency.
# --------------------------------------------------------------------------- #
@pytest.fixture
def af_db_without_transfers(af_db_path):
    """The same fixture database with the transfer objects dropped — exactly
    the shape of a deployed file built before the schema gained them."""
    writer = sqlite3.connect(af_db_path)
    writer.executescript("""
        DROP VIEW  IF EXISTS af_unmapped_transfer_type;
        DROP VIEW  IF EXISTS af_transfer_detail;
        DROP TABLE IF EXISTS af_transfer;
        DROP TABLE IF EXISTS af_transfer_type;
    """)
    writer.commit()
    writer.close()
    return af_db_path


def _connect(path):
    return db_module.connect_af(path)


def test_player_page_survives_a_database_built_before_transfers(af_db_without_transfers):
    """The actual production 500, as a test."""
    connection = _connect(af_db_without_transfers)
    try:
        detail = af_queries.player_detail(connection, 1)
        assert detail is not None
        assert detail["total_absences"] == 3          # the page still works
        assert detail["transfers"]["available"] is False
        assert detail["transfers"]["rows"] == []
    finally:
        connection.close()


def test_team_page_survives_a_database_built_before_transfers(af_db_without_transfers):
    connection = _connect(af_db_without_transfers)
    try:
        detail = af_queries.team_detail(connection, 100)
        assert detail is not None
        assert len(detail["recent"]) == 5             # absences unaffected
        assert detail["transfers"]["available"] is False
        assert detail["transfers"]["incoming"]["rows"] == []
    finally:
        connection.close()


def test_transfer_queries_report_unavailable_rather_than_zero(af_db_without_transfers):
    """Zero is a measurement; "not built" is not. The flag is what lets a
    template tell a reader which one it is looking at."""
    connection = _connect(af_db_without_transfers)
    try:
        assert af_queries.transfers_available(connection) is False
        overview = af_queries.transfer_overview(connection)
        assert overview["available"] is False
        # Every key the template reads must still be present, or the page
        # raises on a missing attribute — the same 500 in a different costume.
        for key in ("moves", "players", "earliest", "latest", "fee_rows",
                    "fee_eur_total", "confirmed_both", "unlinkable_sides",
                    "date_note", "fee_note"):
            assert key in overview
        assert af_queries.transfer_categories(connection) == []
        assert af_queries.transfers_by_year(connection) == []
    finally:
        connection.close()


def test_transfers_available_is_true_for_a_current_build(af_connection):
    """The other direction: the guard must not disable transfers on a database
    that does have them, which would hide the feature instead of a crash."""
    assert af_queries.transfers_available(af_connection) is True
    assert af_queries.player_transfers(af_connection, 1)["available"] is True


def test_transfer_history_is_not_bounded_by_af_league_season(af_connection):
    """The reason this table exists. Every other table here is capped at the
    seasons in af_league_season; transfers are not, and a future join to that
    table would silently discard most of their value."""
    earliest = af_connection.execute(
        "SELECT MIN(date) FROM af_transfer").fetchone()[0]
    min_season = af_connection.execute(
        "SELECT MIN(season) FROM af_league_season").fetchone()[0]
    assert int(earliest[:4]) < min_season
