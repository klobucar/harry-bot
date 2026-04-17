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


def _last_thursday_of_march(year: int) -> datetime.date:
    """Return the date of the last Thursday in March for `year`.

    MLB's Opening Day in the modern era (2018+) has been the last Thursday
    in March — 2024-03-28, 2023-03-30, 2025-03-27, etc. Walk back from
    March 31 to the nearest Thursday.
    """
    march_31 = datetime.date(year, 3, 31)
    # weekday(): Mon=0, Thu=3 → distance back to the most recent Thursday.
    days_back = (march_31.weekday() - 3) % 7
    return march_31 - datetime.timedelta(days=days_back)


def current_season(today: datetime.date | None = None) -> int:
    """
    Return the MLB season year that users most likely want as a default.

    Before Opening Day the current calendar year's leaderboards are empty,
    so default to last season. On or after Opening Day (the last Thursday
    in March in the modern era), switch to the current calendar year.

    This misses unusual years — the 2020 pandemic start, the 2022 lockout
    delay, a mid-March Tokyo series — by a week or two. For those we'd
    need to hit MLB's schedule endpoint at startup; the last-Thursday rule
    is the deterministic fallback that's right for every normal season.

    `today` is injectable for deterministic tests.
    """
    d = today if today is not None else datetime.date.today()
    opening_day = _last_thursday_of_march(d.year)
    if d < opening_day:
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
