"""Read-only access to the derived app database(s)."""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")
# Separate database, separate connection — see app/schema_af.sql for why the
# two vendors are not merged into one schema.
AF_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apifootball.db")


def connect(path=None):
    connection = sqlite3.connect(f"file:{path or DB_PATH}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def connect_af(path=None):
    return connect(path or AF_DB_PATH)


def rows(connection, sql, params=()):
    """Return dictionaries so templates and JSON serialize identically."""
    return [dict(row) for row in connection.execute(sql, params).fetchall()]
