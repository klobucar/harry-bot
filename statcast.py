"""
statcast.py — Backward-compat facade.

The Statcast data/plot layer now sits on top of `bigleague` (async,
polars-native), split across two focused modules:

  * statcast_stats.py — pure-data helpers (player lookup, matchup stats,
    pitch arsenal, hot/cold splits, exit velocity, percentiles, standings,
    schedule).
  * statcast_plots.py — strike-zone, hot-zone, spray-chart, stadium, and
    matchup-zone PNG renderers.

All helpers are now ``async def`` (bigleague is async-native); command
handlers ``await`` them directly. This module re-exports the public surface
so existing imports (``from statcast import resolve_player_id, ...``) keep
working.
"""

from __future__ import annotations

from statcast_plots import (
    _STADIUM_ALIASES,
    _STADIUM_TO_TEAM_CODE,
    _load_known_stadiums,
    _normalize_stadium,
    fetch_batter_zone,
    fetch_hitter_hotzones,
    fetch_matchup_zone,
    fetch_pitcher_zone,
    fetch_spray_chart,
    fetch_stadium_info,
    plot_to_buffer,
)
from statcast_stats import (
    AB_EVENTS,
    HIT_EVENTS,
    compute_matchup_stats,
    fetch_exit_velo,
    fetch_hot_cold,
    fetch_percentile_ranks,
    fetch_pitch_arsenal,
    fetch_player_mlb_years,
    fetch_schedule,
    fetch_standings,
    resolve_player_id,
    season_range,
)

__all__ = [
    "AB_EVENTS",
    "HIT_EVENTS",
    "_STADIUM_ALIASES",
    "_STADIUM_TO_TEAM_CODE",
    "_load_known_stadiums",
    "_normalize_stadium",
    "compute_matchup_stats",
    "fetch_batter_zone",
    "fetch_exit_velo",
    "fetch_hitter_hotzones",
    "fetch_hot_cold",
    "fetch_matchup_zone",
    "fetch_percentile_ranks",
    "fetch_pitch_arsenal",
    "fetch_pitcher_zone",
    "fetch_player_mlb_years",
    "fetch_schedule",
    "fetch_spray_chart",
    "fetch_stadium_info",
    "fetch_standings",
    "plot_to_buffer",
    "resolve_player_id",
    "season_range",
]
