"""
statcast.py — Backward-compat facade.

The implementation now lives in three focused modules:

  * statcast_patch.py — pybaseball lazy init + monkeypatches (UA scope,
    pyarrow read_csv, schedule CoW fix). Holds the lazy-loaded sentinels.
  * statcast_plots.py — strike-zone, hot-zone, spray-chart, stadium, and
    matchup-zone PNG renderers.
  * statcast_stats.py — pure-data helpers (player lookup, matchup stats,
    pitch arsenal, hot/cold splits, exit velocity, percentiles, standings,
    schedule).

This file re-exports the public surface from those modules so existing
imports (``from statcast import fetch_pitcher_zone, ...``) keep working.

Tests that need to mock pybaseball functions should patch them at their
real source (``patch("statcast_patch.statcast_batter", ...)``) — the
helpers in statcast_plots / statcast_stats look them up via attribute
access on statcast_patch.
"""

from __future__ import annotations

from statcast_patch import (
    Figure,
    _init_pybaseball,
    _patch_schedule_make_numeric,
    fast_read_csv,
    fast_read_json,
    playerid_lookup,
    plotting,
    plt,
    schedule_and_record,
    standings,
    statcast_batter,
    statcast_batter_exitvelo_barrels,
    statcast_batter_percentile_ranks,
    statcast_pitcher,
    statcast_pitcher_percentile_ranks,
    statcast_pitcher_pitch_arsenal,
)
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
    "Figure",
    "_init_pybaseball",
    "_load_known_stadiums",
    "_normalize_stadium",
    "_patch_schedule_make_numeric",
    "compute_matchup_stats",
    "fast_read_csv",
    "fast_read_json",
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
    "playerid_lookup",
    "plot_to_buffer",
    "plotting",
    "plt",
    "resolve_player_id",
    "schedule_and_record",
    "season_range",
    "standings",
    "statcast_batter",
    "statcast_batter_exitvelo_barrels",
    "statcast_batter_percentile_ranks",
    "statcast_pitcher",
    "statcast_pitcher_percentile_ranks",
    "statcast_pitcher_pitch_arsenal",
]
