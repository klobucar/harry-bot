"""
commands/autocomplete.py — Shared player-name autocomplete for slash commands.

Data model
----------
A single in-memory cache, keyed by MLBAM ID so a player appearing on multiple
seasons' rosters takes exactly one slot. Name strings are sys.interned so
duplicates ("Aaron", "Garcia", etc.) share backing storage.

    @dataclass(frozen=True, slots=True)
    class Player:
        id: int
        first: str        # sys.interned
        last: str         # sys.interned
        team: str         # 3-letter abbr, e.g. "NYY"
        position: str     # "SP", "OF", etc.

    _cache: dict[int, Player]   # ~2000 entries for a 4-season window

Refresh strategy
----------------
Lazy: the first autocomplete request warms the cache. Subsequent requests
within AUTOCOMPLETE_CACHE_TTL (24h) hit memory only.

Autocomplete callbacks
----------------------
Two callbacks, both exposed for use with @app_commands.autocomplete():
- first_name_autocomplete: prefix-match on first name, narrowed by last name
  if already filled. Returns DISTINCT first names, not duplicates.
- last_name_autocomplete: prefix-match on last name, narrowed by first name
  if already filled. Returns DISTINCT last names.

Display string is "First Last (TEAM POS)" for whichever player(s) match,
but the submitted value is only the single name the user is picking — so
the other field stays free for them to fill.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sys import intern
from typing import TYPE_CHECKING

from discord import app_commands

from mlb_api import fetch_recent_players

if TYPE_CHECKING:
    import discord

log = logging.getLogger("harry")

SEASONS_LOOKBACK = 4  # current year + 3 prior
AUTOCOMPLETE_CACHE_TTL = timedelta(hours=24)
MAX_CHOICES = 25  # Discord's hard cap
MIN_PREFIX_FOR_SEARCH = 0  # 0 lets users see a default list of top 25


@dataclass(frozen=True, slots=True)
class Player:
    id: int
    first: str
    last: str
    team: str
    position: str


def _build_cache(raw: list[dict]) -> dict[int, Player]:
    """Dedup raw records (one per player-season) into {id: Player}.

    Later seasons overwrite earlier ones so each player's team/position
    reflects their most recent roster entry.
    """
    out: dict[int, Player] = {}
    for r in raw:
        pid = r.get("id")
        if not pid:
            continue
        first = (r.get("first") or "").strip()
        last = (r.get("last") or "").strip()
        if not first or not last:
            continue
        out[pid] = Player(
            id=pid,
            first=intern(first),
            last=intern(last),
            team=intern(r.get("team") or ""),
            position=intern(r.get("position") or ""),
        )
    return out


# ---------------------------------------------------------------------------
# Cache state
# ---------------------------------------------------------------------------

_players: dict[int, Player] = {}
_fetched_at: datetime | None = None
_refresh_lock = asyncio.Lock()


def _is_fresh(now: datetime) -> bool:
    return _fetched_at is not None and (now - _fetched_at) < AUTOCOMPLETE_CACHE_TTL


async def _ensure_cache() -> dict[int, Player]:
    """Return the cache, refreshing if stale. Safe to call concurrently."""
    global _players, _fetched_at

    now = datetime.now(tz=UTC)
    if _players and _is_fresh(now):
        return _players

    async with _refresh_lock:
        # Double-check under the lock — another coroutine may have refreshed.
        now = datetime.now(tz=UTC)
        if _players and _is_fresh(now):
            return _players

        seasons = [now.year - i for i in range(SEASONS_LOOKBACK)]
        log.info("Autocomplete: refreshing player cache for seasons %s", seasons)
        try:
            raw = await asyncio.to_thread(fetch_recent_players, seasons)
        except Exception:
            log.exception("Autocomplete: player-cache refresh failed")
            return _players  # return whatever we have (possibly empty)

        _players = _build_cache(raw)
        _fetched_at = now
        log.info("Autocomplete: cached %d unique players", len(_players))
        return _players


# ---------------------------------------------------------------------------
# Pure filter helpers (tested directly — no Discord types involved)
# ---------------------------------------------------------------------------


def filter_first_names(
    players: dict[int, Player],
    prefix: str,
    last_filter: str = "",
    limit: int = MAX_CHOICES,
) -> list[tuple[str, str]]:
    """Distinct first names matching `prefix`, sorted A-Z, capped at `limit`.

    Returns a list of (display_label, submit_value) tuples where display_label
    and submit_value are both the first name itself (e.g. ("Aaron", "Aaron")) —
    when the user is picking a first name, showing a single player's full name
    + team as the label is misleading because many players share the prefix.

    - `prefix` (case-insensitive): filter by first-name prefix.
    - `last_filter` (case-insensitive): if set, only include first names of
      players whose last name starts with it (cross-field narrowing).
    - Iterates the distinct-first-name *set*, not players sorted by last name,
      so that a common prefix like "J" returns a balanced alphabetical slice
      (Jack, Jacob, Jake, Jason, ...) rather than filling all 25 slots with
      last-name-A surnames before any B+ gets a look.
    """
    p_low = prefix.lower().strip()
    l_low = last_filter.lower().strip()

    distinct: set[str] = set()
    for p in players.values():
        if p_low and not p.first.lower().startswith(p_low):
            continue
        if l_low and not p.last.lower().startswith(l_low):
            continue
        distinct.add(p.first)

    ordered = sorted(distinct, key=str.lower)[:limit]
    return [(name, name) for name in ordered]


def filter_last_names(
    players: dict[int, Player],
    prefix: str,
    first_filter: str = "",
    limit: int = MAX_CHOICES,
) -> list[tuple[str, str]]:
    """Distinct last names matching `prefix`, sorted A-Z, capped at `limit`.

    Mirror of filter_first_names with the roles swapped.
    """
    p_low = prefix.lower().strip()
    f_low = first_filter.lower().strip()

    distinct: set[str] = set()
    for p in players.values():
        if p_low and not p.last.lower().startswith(p_low):
            continue
        if f_low and not p.first.lower().startswith(f_low):
            continue
        distinct.add(p.last)

    ordered = sorted(distinct, key=str.lower)[:limit]
    return [(name, name) for name in ordered]


# ---------------------------------------------------------------------------
# Discord autocomplete callbacks
# ---------------------------------------------------------------------------


def _sibling(interaction: discord.Interaction, name: str) -> str:
    """Read a sibling field's current value from the namespace, empty if not set."""
    val = getattr(interaction.namespace, name, None)
    return str(val) if val else ""


def make_first_name_autocomplete(last_field: str = "last_name"):
    """Build a first-name autocomplete callback that narrows by `last_field`.

    Use when a command's last-name parameter is named something other than
    'last_name' (e.g. 'pitcher_last', 'p1_last').
    """

    async def cb(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        players = await _ensure_cache()
        last = _sibling(interaction, last_field)
        pairs = filter_first_names(players, current, last_filter=last)
        return [app_commands.Choice(name=label, value=value) for label, value in pairs]

    return cb


def make_last_name_autocomplete(first_field: str = "first_name"):
    """Build a last-name autocomplete callback that narrows by `first_field`."""

    async def cb(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        players = await _ensure_cache()
        first = _sibling(interaction, first_field)
        pairs = filter_last_names(players, current, first_filter=first)
        return [app_commands.Choice(name=label, value=value) for label, value in pairs]

    return cb


# Default-field callbacks for commands that use the canonical
# `first_name` / `last_name` parameter names.
first_name_autocomplete = make_first_name_autocomplete()
last_name_autocomplete = make_last_name_autocomplete()
