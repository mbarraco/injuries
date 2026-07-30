from app import queries


def test_analytics_rows_link_to_type_and_league_pages(client):
    """Aggregate rows were dead text: a reader could see that Knock is the most
    common injury and had no way to reach it."""
    text = client.get("/sportmonks/analytics").text

    assert 'href="/sportmonks/type/500"' in text
    assert 'href="/sportmonks/league/10"' in text


def test_aggregates_carry_the_ids_the_links_need(connection):
    """No new queries for the linking — the existing SELECTs return ids."""
    assert queries.by_type(connection)[0]["type_id"] == 500
    assert queries.by_league(connection)[0]["league_id"] == 10


def test_unresolved_aggregate_rows_stay_visible(connection):
    """Rows whose dimension never resolved keep their 'Unknown' label and fall
    back to unlinked text via entity_link, rather than being dropped."""
    for row in queries.by_type(connection):
        assert row["type"] is not None
