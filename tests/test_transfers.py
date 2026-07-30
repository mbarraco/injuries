"""Transfer detail: type, fee, and the distinction between kinds of 'no fee'."""
from app import queries


def test_transfer_types_resolve_to_names(connection):
    """Transfer types live in the vendor taxonomy but are never referenced by
    an absence, so resolve.py never stored them and they used to arrive as bare
    ids. etl.collect_types widens the table from the raw types cache."""
    transfers = {row["id"]: row for row in queries.player_timeline(connection, 5001)["transfers"]}

    assert transfers[700]["transfer_type"] == "Transfer"
    assert transfers[701]["transfer_type"] == "Free Transfer"
    assert transfers[702]["transfer_type"] == "Loan"


def test_type_absent_from_the_taxonomy_stays_unnamed(connection):
    """Type 9688 is on thousands of real rows but missing from the vendor's own
    /types list. It must surface as unnamed rather than be guessed at."""
    transfers = {row["id"]: row for row in queries.player_timeline(connection, 5001)["transfers"]}

    assert transfers[703]["type_id"] == 9688
    assert transfers[703]["transfer_type"] is None


def test_fee_is_exposed_with_a_reported_flag(connection):
    """`fee_reported` separates a disclosed fee from an absent one, so the
    template never has to infer intent from a null."""
    transfers = {row["id"]: row for row in queries.player_timeline(connection, 5001)["transfers"]}

    assert transfers[700]["amount"] == 5000000
    assert transfers[700]["fee_reported"] == 1
    assert transfers[701]["amount"] is None
    assert transfers[701]["fee_reported"] == 0


def test_summary_totals_only_disclosed_fees_and_says_how_many(connection):
    """A career fee total is meaningless without the count it rests on: most
    moves report no fee, so an unqualified total reads as complete."""
    summary = queries.player_timeline(connection, 5001)["transfer_summary"]

    assert summary["moves"] == 4
    assert summary["total_fees"] == 5000000
    assert summary["fees_known"] == 1        # the total covers 1 of 4 moves
    assert summary["free_transfers"] == 1
    assert summary["loans"] == 1


def test_player_page_shows_type_and_fee(client):
    body = client.get("/sportmonks/player/5001").text

    assert "Free Transfer" in body
    assert "Loan" in body
    assert "5,000,000" in body
    assert "free" in body          # the free transfer is labelled, not blank
    assert "undisclosed" in body   # the loan's absent fee is marked as such


def test_free_transfer_is_not_presented_as_missing_data(client):
    """A free transfer HAS no fee; a loan with no disclosed fee is unknown.
    Rendering both as an empty cell would misreport the first as a gap."""
    body = client.get("/sportmonks/player/5001").text

    assert 'title="A free transfer has no fee"' in body
    assert 'title="No fee disclosed for this move"' in body


def test_team_page_reports_spend_with_its_basis(client):
    body = client.get("/sportmonks/team/100").text

    assert "disclosed fees" in body
    assert "5,000,000" in body
