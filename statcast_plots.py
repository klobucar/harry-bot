"""
statcast_plots.py — Statcast PNG renderers (strike-zone, hot-zone, spray
chart, stadium, matchup-zone).

A thin **async facade** over `bigleague`: data fetches are awaited
(async-native, polars), and the CPU-bound matplotlib render is offloaded to
a worker thread via ``asyncio.to_thread`` so it never blocks the Discord
event loop. bigleague's plot helpers return raw PNG ``bytes``; we wrap them
in ``BytesIO`` so the command layer keeps passing ``discord.File(fp=buf)``
unchanged.
"""

from __future__ import annotations

import asyncio
from io import BytesIO

import bigleague
import polars as pl
from bigleague import plots
from bigleague.stadiums import STADIUM_ALIASES, STADIUM_TO_TEAM_CODE
from bigleague.stadiums import known_stadiums as _load_known_stadiums
from bigleague.stadiums import metadata as _stadium_metadata
from bigleague.stadiums import normalize as _normalize_stadium

# Back-compat re-exports for the names statcast.py historically surfaced.
_STADIUM_ALIASES = STADIUM_ALIASES
_STADIUM_TO_TEAM_CODE = STADIUM_TO_TEAM_CODE

__all__ = [
    "_STADIUM_ALIASES",
    "_STADIUM_TO_TEAM_CODE",
    "_load_known_stadiums",
    "_normalize_stadium",
    "fetch_batter_zone",
    "fetch_hitter_hotzones",
    "fetch_matchup_zone",
    "fetch_pitcher_zone",
    "fetch_spray_chart",
    "fetch_stadium_info",
    "plot_to_buffer",
]


async def plot_to_buffer(df: pl.DataFrame, title: str, colorby: str = "pitch_type") -> BytesIO:
    """Render a strike-zone scatter from a Statcast frame and return a PNG buffer.

    Raises ValueError if the frame is empty.
    """
    if df is None or df.is_empty():
        raise ValueError("Cannot plot an empty dataset.")
    png = await asyncio.to_thread(plots.strike_zone, df, title, colorby)
    return BytesIO(png)


async def fetch_pitcher_zone(player_id: int, year: int, player_name: str) -> BytesIO:
    """Full-season pitcher strike-zone PNG. Raises ValueError if no data."""
    df = await bigleague.statcast_season(player_id, year, "pitcher")
    if df.is_empty():
        raise ValueError(f"No Statcast pitcher data for player_id={player_id} in {year}.")
    png = await asyncio.to_thread(plots.strike_zone, df, f"{player_name} — {year} Strike Zone")
    return BytesIO(png)


async def fetch_batter_zone(player_id: int, year: int, player_name: str) -> BytesIO:
    """Full-season strike-zone PNG of pitches received. Raises ValueError if no data."""
    df = await bigleague.statcast_season(player_id, year, "batter")
    if df.is_empty():
        raise ValueError(f"No Statcast batter data for player_id={player_id} in {year}.")
    png = await asyncio.to_thread(plots.batter_zone, df, f"{player_name} — {year} Pitches Received")
    return BytesIO(png)


async def fetch_hitter_hotzones(player_id: int, year: int, player_name: str) -> BytesIO:
    """3x3 batting-average hot-zone heatmap PNG. Raises ValueError if no data."""
    df = await bigleague.statcast_season(player_id, year, "batter")
    if df.is_empty():
        raise ValueError(f"No Statcast batter data for {player_name} in {year}.")
    title = f"Hitter Hot Zones: {player_name} ({year})\n(Batting Average by Zone)"
    png = await asyncio.to_thread(plots.hot_zones, df, title)
    return BytesIO(png)


async def fetch_matchup_zone(
    pitcher_id: int,
    batter_id: int,
    year: int,
    pitcher_name: str,
    batter_name: str,
) -> BytesIO:
    """Strike-zone PNG of a head-to-head matchup (pitches from one pitcher to
    one batter). Raises ValueError if the batter has no data or the two never
    faced each other in the season.
    """
    df = await bigleague.statcast_season(batter_id, year, "batter")
    if df.is_empty():
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")
    matchup = df.filter(pl.col("pitcher") == pitcher_id)
    if matchup.is_empty():
        raise ValueError(
            f"No pitches found from pitcher {pitcher_id} to batter {batter_id} in {year}."
        )
    png = await asyncio.to_thread(
        plots.matchup_zone, matchup, f"{batter_name} vs. {pitcher_name} — {year}"
    )
    return BytesIO(png)


async def fetch_spray_chart(
    batter_id: int, year: int, batter_name: str, team_stadium: str = "generic"
) -> BytesIO:
    """Spray chart PNG overlaid on a stadium. When a non-generic stadium is
    given, bigleague filters batted balls to home games at that park.

    Raises ValueError if no batted-ball data is found.
    """
    df = await bigleague.statcast_season(batter_id, year, "batter")
    if df.is_empty():
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")

    stadium_key = _normalize_stadium(team_stadium)
    title = (
        f"{batter_name} — {year} @ {team_stadium.title()}"
        if stadium_key != "generic"
        else f"{batter_name} — {year} Spray Chart"
    )
    try:
        png = await asyncio.to_thread(plots.spray_chart, df, title, stadium_key)
    except ValueError as exc:
        raise ValueError(
            f"No batted-ball events with coordinates for {batter_name} in {year}."
        ) from exc
    return BytesIO(png)


async def fetch_stadium_info(team_alias: str) -> dict:
    """Stadium name, location, and an outline PNG for a team.

    Returns {"name": str, "location": str, "image": BytesIO}.
    Raises ValueError for an unknown team/stadium.
    """
    stadium_key = _normalize_stadium(team_alias)
    if stadium_key == "generic" and team_alias.lower() != "generic":
        raise ValueError(f"Unknown team/stadium: {team_alias!r}")

    meta = _stadium_metadata(stadium_key)
    name = str(meta.get("name", "Unknown Stadium"))
    location = str(meta.get("location", "Unknown Location"))

    png = await asyncio.to_thread(plots.stadium_outline, stadium_key, name)
    return {"name": name, "location": location, "image": BytesIO(png)}
