"""
abs.py — Async facade over `bigleague.abs`.

Automated Ball-Strike challenge data from Baseball Savant. The fetch +
parse layer now lives in bigleague (async, polars, fetched through Savant's
shared client/semaphore). These aliases preserve the names the command
layer imports; they are now ``async`` and awaited directly.
"""

from __future__ import annotations

from bigleague.abs import (
    PLAYER_ROLES,
    ROLE_BATTER,
    ROLE_CATCHER,
    ROLE_PITCHER,
    ROLE_TEAM_SUMMARY,
    normalize_team,
)
from bigleague.abs import (
    league_leaders as fetch_league_leaders,
)
from bigleague.abs import (
    player as fetch_player,
)
from bigleague.abs import (
    team_summary as fetch_team_summary,
)
from bigleague.abs import (
    team_top_challengers as fetch_team_top_challengers,
)

__all__ = [
    "PLAYER_ROLES",
    "ROLE_BATTER",
    "ROLE_CATCHER",
    "ROLE_PITCHER",
    "ROLE_TEAM_SUMMARY",
    "fetch_league_leaders",
    "fetch_player",
    "fetch_team_summary",
    "fetch_team_top_challengers",
    "normalize_team",
]
