from app import queries


def test_coverage_ramp_reads_the_yearly_metrics(connection):
    """The `coverage_<year>` rows become a series the page can chart, instead
    of opaque rows in the generic metrics table."""
    ramp = queries.coverage_ramp(connection)

    assert [row["year"] for row in ramp] == [2025]
    assert ramp[0]["per_fixture"] == 2.0  # 4 sidelined rows across 2 fixtures


def test_coverage_totals_replace_the_three_year_pivot(connection):
    """Year 1 / Year 2 / Year 3 encoded a 3-year model; competitions have
    different depths by design, so depth is reported as the actual span."""
    totals = queries.coverage_totals(connection)

    assert totals[0]["league"] == "Test League"
    assert totals[0]["records"] == 500
    assert totals[0]["league_id"] == 10  # linkable, unlike the old text-only table


def test_coverage_page_drops_the_settled_claim(client):
    """This was settled on 2026-07-27: the depth limit is the plan, measured,
    not a suspicion about the account tier."""
    text = client.get("/coverage").text

    assert "History depth is provisional" not in text
    assert "trial-account" not in text
    assert "Year 1" not in text


def test_coverage_page_states_the_measured_limit(client):
    text = client.get("/coverage").text

    assert "3 seasons" in text
    assert "2000" in text  # the cups' reach


def test_coverage_page_charts_the_ramp_with_the_mix_caveat(client):
    text = client.get("/coverage").text

    assert "coverageRamp" in text  # the chart canvas
    assert "2024" in text          # the year the series composition changes
    assert "58 domestic leagues" in text


def test_coverage_api_is_unchanged(client):
    """/api/coverage keeps returning the year-bucket pivot: the page changed,
    the documented endpoint did not."""
    body = client.get("/api/coverage").json()

    assert body["leagues"][0]["league"] == "Test League"
    assert "yr3" in body["leagues"][0]
