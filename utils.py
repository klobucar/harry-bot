"""
utils.py — Shared utilities: year validation, current-season helper.

No Discord, no pybaseball imports. Pure Python — safe to use everywhere.
"""

from __future__ import annotations

import datetime

# Statcast data begins mid-2015 (full season from 2016, but 2015 is usable)
STATCAST_MIN_YEAR: int = 2015
# FanGraphs data is reliable from 2002
FANGRAPHS_MIN_YEAR: int = 2002


def current_year() -> int:
    """Return the current calendar year."""
    return datetime.datetime.now().year


def current_season(today: datetime.date | None = None) -> int:
    """
    Return the MLB season year that users most likely want as a default.

    Before April 1 the current calendar year's Opening Day either hasn't
    happened yet or is only a game or two old, and FanGraphs / Statcast
    leaderboards are effectively empty — so we default to last year. On
    April 1 and after, we switch to the current calendar year.

    Opening Day floats between the last week of March (sometimes a
    Tokyo-series game in mid-March); April 1 is the cleanest rule that
    avoids per-year calibration against MLB's schedule endpoint.

    `today` is injectable for deterministic tests.
    """
    d = today if today is not None else datetime.date.today()
    if d.month < 4:
        return d.year - 1
    return d.year


def validate_statcast_year(year: int) -> str | None:
    """
    Validate a year for Statcast commands (/strikezone, /battedzone, /spraychart,
    /arsenal, /exitvelo, /hotcold, /percentile, matchup zone commands).

    Returns an error string if invalid, or None if the year is acceptable.
    """
    cy = current_year()
    if year < STATCAST_MIN_YEAR:
        return (
            f"Statcast data only goes back to {STATCAST_MIN_YEAR}. "
            f"{year} is before the Statcast era — "
            "I'm good, but I'm not a time machine."
        )
    if year > cy:
        return f"{year} hasn't happened yet. Even I can't announce the future."
    return None


def validate_fangraphs_year(year: int) -> str | None:
    """
    Validate a year for FanGraphs commands (/stats, /compare, /career, /leaderboard).

    Returns an error string if invalid, or None if the year is acceptable.
    """
    cy = current_year()
    if year < FANGRAPHS_MIN_YEAR:
        return (
            f"FanGraphs data only goes back to {FANGRAPHS_MIN_YEAR}. "
            f"{year} is ancient history — try the Lahman database."
        )
    if year > cy:
        return f"{year} hasn't happened yet. Even I can't announce the future."
    return None


def validate_year_range(start: int, end: int, min_year: int = FANGRAPHS_MIN_YEAR) -> str | None:
    """Validate a year range. Returns error string or None."""
    cy = current_year()
    if start < min_year:
        return f"Start year must be {min_year} or later."
    if end > cy:
        return f"End year {end} is in the future."
    if start > end:
        return f"Start year ({start}) can't be after end year ({end})."
    return None
