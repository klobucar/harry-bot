"""
fangraphs.py — Async facade over `bigleague.fangraphs`.

FanGraphs data (season leaderboards, per-player stats, career aggregates)
now comes from bigleague, which fetches fangraphs.com through curl_cffi with
Chrome TLS fingerprinting to pass the Cloudflare gate. These wrappers keep
the names/shapes the command layer already imports; they are now ``async``
and awaited directly. No pandas — bigleague is polars-native.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from bigleague import fangraphs as _fg
from bigleague.fangraphs import FangraphsBlockedError
from bigleague.stats import aggregate_career

if TYPE_CHECKING:
    import polars as pl

__all__ = [
    "FangraphsBlockedError",
    "LeaderboardPlayerType",
    "PlayerType",
    "aggregate_career_frames",
    "fetch_career_stats",
    "fetch_leaderboard",
    "fetch_player_stats",
    "fetch_player_stats_compare",
    "fetch_year_fangraphs",
    "player_role_blocks",
]

PlayerType = Literal["pitcher", "batter"]
LeaderboardPlayerType = Literal["pitcher", "batter", "auto"]


async def fetch_player_stats(first: str, last: str, year: int) -> dict:
    """Season FanGraphs stats for a player, auto-detecting pitcher vs batter.

    Single-role players return {"type", "team", "stats"}; two-way players
    return {"type": "two-way", "roles": {"pitcher": ..., "batter": ...}}.
    Raises ValueError if not found.
    """
    return await _fg.player_stats(first, last, year)


async def fetch_player_stats_compare(first: str, last: str, year: int) -> dict:
    """Thin alias used by /compare — identical to fetch_player_stats."""
    return await fetch_player_stats(first, last, year)


async def fetch_career_stats(first: str, last: str) -> dict:
    """Career aggregate FanGraphs stats (auto-detect), full career range."""
    return await _fg.career_stats(first, last)


async def fetch_year_fangraphs(
    yr: int, player_type: PlayerType, first: str, last: str
) -> pl.DataFrame | None:
    """One year of FanGraphs pitching/batting stats for a player.

    Returns a polars frame tagged with a `_year` column, or None on no-data.
    Request and parsing failures propagate so callers cannot emit partial
    career totals.
    """
    return await _fg.player_stats_for_year(first, last, yr, player_type)


def player_role_blocks(result: dict[str, Any]) -> dict[PlayerType, dict[str, Any]]:
    """Normalize bigleague's single-role/two-way union into role blocks."""
    result_type = result.get("type")
    if result_type == "two-way":
        raw_roles = result.get("roles")
        if not isinstance(raw_roles, dict):
            raise ValueError("Malformed two-way FanGraphs result: missing roles")
        roles: dict[PlayerType, dict[str, Any]] = {}
        for role in ("pitcher", "batter"):
            block = raw_roles.get(role)
            if isinstance(block, dict):
                roles[role] = block
        if not roles:
            raise ValueError("Malformed two-way FanGraphs result: no role data")
        return roles
    if result_type not in ("pitcher", "batter"):
        raise ValueError(f"Malformed FanGraphs result type: {result_type!r}")
    return {
        result_type: {
            "team": result.get("team", "N/A"),
            "stats": result.get("stats", {}),
        }
    }


def aggregate_career_frames(
    pitch_frames: list[pl.DataFrame],
    bat_frames: list[pl.DataFrame],
    first: str,
    last: str,
    years: list[int],
) -> dict:
    """Pure aggregation (no I/O): combine per-year frames into a career summary.

    Returns both role blocks when both frame sets contain the player.
    """
    pitcher = (
        aggregate_career(pitch_frames, first, last, years, "pitcher") if pitch_frames else None
    )
    batter = aggregate_career(bat_frames, first, last, years, "batter") if bat_frames else None
    if pitcher is not None and batter is not None:
        return {
            "type": "two-way",
            "roles": {
                "pitcher": {"team": pitcher["team"], "stats": pitcher["stats"]},
                "batter": {"team": batter["team"], "stats": batter["stats"]},
            },
        }
    if pitcher is not None:
        return pitcher
    if batter is not None:
        return batter
    raise ValueError(f"No FanGraphs data found for {first} {last} in {years[0]}-{years[-1]}.")


async def fetch_leaderboard(
    stat: str,
    year: int,
    player_type: LeaderboardPlayerType = "auto",
) -> list[dict[str, Any]]:
    """Top 10 players for a FanGraphs stat in a season.

    Returns list of {rank, name, team, value}. bigleague infers the sort
    direction (lower-is-better stats like ERA sort ascending).
    """
    return await _fg.top_leaderboard(stat, year, 10, player_type)
