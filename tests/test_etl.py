import sqlite3

from app import etl


def test_dedupes_and_filters_absences(tmp_path, raw_cache_dir, reference_db):
    output = tmp_path / "app.db"
    result = etl.build(raw_cache_dir, reference_db, output)
    connection = sqlite3.connect(output)
    assert connection.execute("SELECT id, fixture_appearances FROM injury ORDER BY id").fetchall() == [(900, 2), (902, 1)]
    assert result["excluded"] == {"suspended": 1}


def test_derives_fields_and_quality_metrics(tmp_path, raw_cache_dir, reference_db):
    output = tmp_path / "app.db"
    etl.build(raw_cache_dir, reference_db, output)
    connection = sqlite3.connect(output)
    assert connection.execute("SELECT duration_days, age_at_start, is_ongoing FROM injury WHERE id = 900").fetchone() == (59, 25.1, 0)
    assert connection.execute("SELECT duration_days, is_ongoing FROM injury WHERE id = 902").fetchone() == (None, 1)
    metrics = dict(connection.execute("SELECT metric, value FROM data_quality"))
    assert {key: metrics[key] for key in ("raw_pivot_rows", "distinct_absences", "injuries", "excluded_suspended")} == {"raw_pivot_rows": 4.0, "distinct_absences": 3.0, "injuries": 2.0, "excluded_suspended": 1.0}
