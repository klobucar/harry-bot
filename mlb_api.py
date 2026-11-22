"""
mlb_api.py — Async facade over `bigleague.mlb`.

The official MLB Stats API layer (roster, injuries, transactions, live
scores, next game, recent results, standings, player rosters) now lives in
bigleague, which talks to statsapi.mlb.com over async httpx with retries.

These thin aliases preserve the names the bot already imports; they are now
``async`` and awaited directly (no more ``asyncio.to_thread``). ``TEAM_IDS``
and ``POS_NAMES`` are re-exported unchanged.
"""

from __future__ import annotations

from bigleague.mlb import (
    POS_NAMES,
    TEAM_IDS,
)
from bigleague.mlb import (
    injuries as fetch_injuries,
)
from bigleague.mlb import (
    live_scores as fetch_live_scores,
)
from bigleague.mlb import (
    next_game as fetch_next_game,
)
from bigleague.mlb import (
    players as fetch_players,
)
from bigleague.mlb import (
    players_multi_season as fetch_recent_players,
)
from bigleague.mlb import (
    recent_results as fetch_recent_results,
)
from bigleague.mlb import (
    roster as fetch_roster,
)
from bigleague.mlb import (
    standings as fetch_standings,
)
from bigleague.mlb import (
    transactions as fetch_transactions,
)

__all__ = [
    "POS_NAMES",
    "TEAM_IDS",
    "fetch_injuries",
    "fetch_live_scores",
    "fetch_next_game",
    "fetch_players",
    "fetch_recent_players",
    "fetch_recent_results",
    "fetch_roster",
    "fetch_standings",
    "fetch_transactions",
]
