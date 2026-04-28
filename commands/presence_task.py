"""
commands/presence_task.py — Team-aware, schedule-smart Discord presence.

A small state machine drives a single long-running asyncio task that sleeps
just long enough to catch the next interesting moment:

    LIVE      -> 60s poll       (responsive score updates)
    WARMUP    -> 120s poll      (Warmup / Pre-Game / Delayed Start)
    SCHEDULED -> sleep until 15 min before first pitch
    POST_GAME -> linger on the final for 1 hour, then sleep until morning
    NO_GAME   -> sleep until 10 AM local the next day
    error     -> 5 min retry

Off-days cost ~1 API call per morning instead of 288 per day.

Configurable per-team via env:
    PRESENCE_TEAM        (default "DET")
    PRESENCE_TZ          (default "America/New_York")
    PRESENCE_DEFAULT_MSG (default "Juuust a bit outside.")
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from mlb_api import fetch_live_scores

log = logging.getLogger("harry")

# --- Config (env-driven with sensible Tigers defaults) --------------------------
TEAM: str = os.environ.get("PRESENCE_TEAM", "DET").upper()
TZ: ZoneInfo = ZoneInfo(os.environ.get("PRESENCE_TZ", "America/New_York"))
DEFAULT_MSG: str = os.environ.get("PRESENCE_DEFAULT_MSG", "Juuust a bit outside.")

# --- Cadence knobs --------------------------------------------------------------
LIVE_POLL_SECS = 60
WARMUP_POLL_SECS = 120
WAKE_BEFORE_FIRST_PITCH_SECS = 15 * 60
ERROR_RETRY_SECS = 300
MORNING_HOUR_LOCAL = 10
FINAL_LINGER_SECS = 60 * 60  # keep the final score visible for 1 hour

# Status buckets — matched as substrings so variants like "Completed Early" land
# in the right place. Order matters in classify_game(): WARMUP is checked before
# LIVE so "Delayed Start" doesn't short-circuit into LIVE on the word "Delayed".
LIVE_STATES = ("In Progress", "Live", "Delayed")
WARMUP_STATES = ("Warmup", "Pre-Game", "Delayed Start")
FINAL_STATES = (
    "Final",
    "Game Over",
    "Completed Early",
    "Postponed",
    "Cancelled",
    "Suspended",
)

# City prefixes for MLB team "full name" → short name stripping. Covers every
# active franchise; ordered longest-first so "New York Yankees" strips before a
# hypothetical "New" prefix match.
_MLB_CITY_PREFIXES: tuple[str, ...] = (
    "Arizona",
    "Atlanta",
    "Baltimore",
    "Boston",
    "Chicago",
    "Cincinnati",
    "Cleveland",
    "Colorado",
    "Detroit",
    "Houston",
    "Kansas City",
    "Los Angeles",
    "Miami",
    "Milwaukee",
    "Minnesota",
    "New York",
    "Oakland",
    "Philadelphia",
    "Pittsburgh",
    "San Diego",
    "San Francisco",
    "Seattle",
    "St. Louis",
    "Tampa Bay",
    "Texas",
    "Toronto",
    "Washington",
)


class GameState(Enum):
    NO_GAME = "no_game"
    SCHEDULED = "scheduled"
    WARMUP = "warmup"
    LIVE = "live"
    POST_GAME = "post_game"


# ---------------------------------------------------------------------------
# Pure decision helpers
# ---------------------------------------------------------------------------


def short_team_name(full: str) -> str:
    """Drop the city prefix from an MLB team name. 'Detroit Tigers' -> 'Tigers'."""
    for city in _MLB_CITY_PREFIXES:
        prefix = city + " "
        if full.startswith(prefix):
            return full[len(prefix) :]
    return full


def pick_active_game(games: list[dict]) -> dict | None:
    """Return the first not-yet-final game (handles doubleheaders). Else last, else None."""
    if not games:
        return None
    for g in games:
        status = g.get("status") or ""
        if not any(s in status for s in FINAL_STATES):
            return g
    return games[-1]


def classify_game(game: dict, now: datetime | None = None) -> GameState:
    """Map an MLB detailedState string to a GameState bucket.

    When `now` is provided, a game whose status is still "Scheduled" or
    "Preview" but whose scheduled start has already passed is upgraded to
    WARMUP. MLB's detailedState flips Scheduled → Warmup → Pre-Game → In
    Progress on the broadcast's cue, which can lag the wall clock by a
    few minutes — without this, the presence line keeps lying about first
    pitch being in the past.
    """
    status = game.get("status") or ""
    if any(s in status for s in WARMUP_STATES):
        return GameState.WARMUP
    if any(s in status for s in LIVE_STATES):
        return GameState.LIVE
    if any(s in status for s in FINAL_STATES):
        return GameState.POST_GAME
    if now is not None:
        start_str = game.get("start_time")
        if start_str:
            try:
                start = datetime.fromisoformat(start_str)
                if now >= start:
                    return GameState.WARMUP
            except ValueError, TypeError:
                pass
    return GameState.SCHEDULED


def seconds_until_next_morning(
    now: datetime,
    hour: int = MORNING_HOUR_LOCAL,
    tz: ZoneInfo | None = None,
) -> float:
    """Seconds from `now` until `hour`:00 the next day in `tz` (default: PRESENCE_TZ)."""
    zone = tz if tz is not None else TZ
    now_local = now.astimezone(zone)
    target = now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now_local:
        target = target + timedelta(days=1)
    return (target - now_local).total_seconds()


def delay_for(state: GameState, game: dict | None, now: datetime) -> float:
    """How long (seconds) to sleep before the next poll, given state. POST_GAME linger is handled in the Cog."""
    if state == GameState.LIVE:
        return LIVE_POLL_SECS
    if state == GameState.WARMUP:
        return WARMUP_POLL_SECS
    if state == GameState.SCHEDULED and game:
        start_str = game.get("start_time")
        if start_str:
            start = datetime.fromisoformat(start_str)
            wake = start - timedelta(seconds=WAKE_BEFORE_FIRST_PITCH_SECS)
            delta = (wake - now).total_seconds()
            return max(LIVE_POLL_SECS, delta)
    return seconds_until_next_morning(now)


def remaining_linger_secs(elapsed_since_final: float) -> float:
    """Seconds of post-game linger window still remaining; 0 if expired."""
    return max(0.0, FINAL_LINGER_SECS - elapsed_since_final)


# ---------------------------------------------------------------------------
# Presence formatters — each returns (Activity, Status)
# ---------------------------------------------------------------------------


def _live_presence(game: dict) -> tuple[discord.BaseActivity, discord.Status]:
    away = short_team_name(str(game.get("away_team", "")))
    home = short_team_name(str(game.get("home_team", "")))
    outs = game.get("outs", 0)
    inning = str(game.get("inning", "")).strip()
    msg = (
        f"🔴 {away} {game.get('away_score', 0)} @ "
        f"{home} {game.get('home_score', 0)} • {inning} • {outs} out"
    )
    return (
        discord.Activity(type=discord.ActivityType.watching, name=msg[:128]),
        discord.Status.online,
    )


def _warmup_presence(game: dict) -> tuple[discord.BaseActivity, discord.Status]:
    away = short_team_name(str(game.get("away_team", "")))
    home = short_team_name(str(game.get("home_team", "")))
    msg = f"⚾ Warmup — {away} @ {home}"
    return (
        discord.Activity(type=discord.ActivityType.watching, name=msg[:128]),
        discord.Status.online,
    )


def _scheduled_presence(game: dict) -> tuple[discord.BaseActivity, discord.Status]:
    away = short_team_name(str(game.get("away_team", "")))
    home = short_team_name(str(game.get("home_team", "")))
    start_str = game.get("start_time")
    if start_str:
        dt = datetime.fromisoformat(start_str).astimezone(TZ)
        t_str = dt.strftime("%-I:%M %p").lower()
        tz_abbr = dt.tzname() or ""
        msg = f"⏰ {away} @ {home} — {t_str} {tz_abbr}".rstrip()
    else:
        msg = f"⏰ Upcoming: {away} @ {home}"
    return (
        discord.Game(name=msg[:128]),
        discord.Status.idle,
    )


def _final_presence(game: dict) -> tuple[discord.BaseActivity, discord.Status]:
    away = short_team_name(str(game.get("away_team", "")))
    home = short_team_name(str(game.get("home_team", "")))
    msg = f"🏁 FINAL — {away} {game.get('away_score', 0)}, {home} {game.get('home_score', 0)}"
    return (
        discord.Activity(type=discord.ActivityType.watching, name=msg[:128]),
        discord.Status.idle,
    )


def _default_presence() -> tuple[discord.BaseActivity, discord.Status]:
    return (discord.Game(name=DEFAULT_MSG), discord.Status.idle)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class PresenceTask(commands.Cog):
    """Schedule-aware, team-configurable presence updater."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task[Any] | None = None
        self._final_game_pk: int | None = None
        self._final_first_seen_at: datetime | None = None

    async def cog_load(self) -> None:
        log.info(
            "Presence task: tracking team=%s tz=%s (linger=%ds)",
            TEAM,
            TZ,
            FINAL_LINGER_SECS,
        )
        self._task = asyncio.create_task(self._run(), name="presence_updater")

    async def cog_unload(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _run(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                delay = await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Presence task tick failed")
                delay = ERROR_RETRY_SECS
            log.info("Presence: sleeping %.0fs before next check", delay)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise

    async def _tick(self) -> float:  # noqa: PLR0911 — state machine naturally fans out
        """One decision cycle: fetch, pick a state, update presence, return next-sleep seconds."""
        now = datetime.now(tz=UTC)

        try:
            games = await asyncio.to_thread(fetch_live_scores, TEAM)
        except ValueError:
            await self._go_idle()
            return seconds_until_next_morning(now)

        game = pick_active_game(games)
        if game is None:
            await self._go_idle()
            return seconds_until_next_morning(now)

        state = classify_game(game, now)

        if state == GameState.LIVE:
            self._clear_linger()
            await self._set_presence(*_live_presence(game))
            return LIVE_POLL_SECS

        if state == GameState.WARMUP:
            self._clear_linger()
            await self._set_presence(*_warmup_presence(game))
            return WARMUP_POLL_SECS

        if state == GameState.SCHEDULED:
            self._clear_linger()
            await self._set_presence(*_scheduled_presence(game))
            return delay_for(state, game, now)

        # POST_GAME — linger on the final for up to FINAL_LINGER_SECS
        game_pk = game.get("game_pk")
        if self._final_game_pk != game_pk:
            self._final_game_pk = game_pk
            self._final_first_seen_at = now

        first_seen = self._final_first_seen_at or now
        elapsed = (now - first_seen).total_seconds()
        remaining = remaining_linger_secs(elapsed)

        if remaining > 0:
            await self._set_presence(*_final_presence(game))
            # Wake at linger end OR next morning, whichever is sooner
            return min(remaining, seconds_until_next_morning(now))

        # Linger expired — revert to default, sleep until morning
        await self._go_idle()
        return seconds_until_next_morning(now)

    async def _go_idle(self) -> None:
        self._clear_linger()
        await self._set_presence(*_default_presence())

    def _clear_linger(self) -> None:
        self._final_game_pk = None
        self._final_first_seen_at = None

    async def _set_presence(
        self,
        activity: discord.BaseActivity,
        status: discord.Status,
    ) -> None:
        try:
            await self.bot.change_presence(activity=activity, status=status)
        except Exception:
            log.exception("change_presence failed")
