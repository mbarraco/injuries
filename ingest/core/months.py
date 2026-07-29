"""Calendar-month arithmetic shared by the fetch runners.

A "window" is a `(d1, d2)` pair of ISO dates where d2 is the exclusive first
day of the next month — the exact shape Sportmonks' `/fixtures/between/d1/d2`
expects. Working in whole calendar months (rather than each country's own
football-season boundaries) avoids guessing 53 different season calendars;
the trade-off is a coverage-level, not season-exact, granularity.

Pure functions only, so the runners' date logic is testable without a clock
or the network.
"""
from __future__ import annotations

from datetime import date


def _first_of_next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _prev_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def parse_ym(year_month):
    """'2024-03' -> (2024, 3). Raises ValueError on a malformed value."""
    year, month = year_month.split("-")
    year, month = int(year), int(month)
    if not 1 <= month <= 12:
        raise ValueError(f"month out of range: {year_month}")
    return year, month


def current_ym(today=None):
    today = today or date.today()
    return f"{today.year:04d}-{today.month:02d}"


def window_for(year, month):
    """The (start, end-exclusive) ISO window covering one calendar month."""
    ny, nm = _first_of_next_month(year, month)
    return f"{year:04d}-{month:02d}-01", f"{ny:04d}-{nm:02d}-01"


def windows_between(start_ym, end_ym):
    """All monthly windows from start_ym to end_ym inclusive, oldest first.

    An empty list if start_ym is after end_ym, so callers can treat
    "nothing to fetch" uniformly without a special case.
    """
    year, month = parse_ym(start_ym)
    end_year, end_month = parse_ym(end_ym)
    windows = []
    while (year, month) <= (end_year, end_month):
        windows.append(window_for(year, month))
        year, month = _first_of_next_month(year, month)
    return windows


def recent_windows(n_months, end_ym=None):
    """The n_months most-recent windows ending at end_ym (default: now)."""
    end_ym = end_ym or current_ym()
    end_year, end_month = parse_ym(end_ym)
    year, month = end_year, end_month
    for _ in range(n_months - 1):
        year, month = _prev_month(year, month)
    return windows_between(f"{year:04d}-{month:02d}", end_ym)


def next_ym(year_month):
    """The month after year_month: '2024-12' -> '2025-01'."""
    year, month = parse_ym(year_month)
    ny, nm = _first_of_next_month(year, month)
    return f"{ny:04d}-{nm:02d}"
