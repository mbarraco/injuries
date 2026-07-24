import pytest

from app import db, etl, queries


@pytest.fixture
def connection(tmp_path, raw_cache_dir, reference_db):
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output)
    value = db.connect(output)
    yield value
    value.close()


def test_overview_and_quality(connection):
    assert queries.overview(connection)["injuries"] == 2
    assert queries.overview(connection)["earliest"] == "2025-02-01"
    assert {metric["metric"] for metric in queries.quality_metrics(connection)} >= {"dedup_ratio", "injuries"}


def test_analytics_queries_join_dimensions(connection):
    assert {row["position"]: row["injuries"] for row in queries.by_position(connection)} == {"Defender": 1, "Forward": 1}
    assert {row["band"]: row["injuries"] for row in queries.by_age_band(connection)} == {"25-29": 2}
    assert queries.by_type(connection)[0]["type"] == "Knock"


def test_injury_list_and_player_timeline(connection):
    result = queries.injury_list(connection, ongoing_only=True)
    assert result["total"] == 1 and result["items"][0]["id"] == 902
    assert queries.injury_list(connection, per_page=1)["total"] == 2
    assert queries.player_timeline(connection, 5001)["player"]["name"] == "A. Player"
