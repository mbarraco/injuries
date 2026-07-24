"""Read-only access to the derived app database."""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")


def connect(path=None):
    connection = sqlite3.connect(f"file:{path or DB_PATH}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def rows(connection, sql, params=()):
    """Return dictionaries so templates and JSON serialize identically."""
    return [dict(row) for row in connection.execute(sql, params).fetchall()]
