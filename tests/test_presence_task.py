"""
tests/test_presence_task.py — Unit tests for the presence state machine.

All tests exercise pure decision/formatter functions; no discord mocks, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import discord
import pytest

from commands.presence_task import (
    FINAL_LINGER_SECS,
    LIVE_POLL_SECS,
    MORNING_HOUR_LOCAL,
    WAKE_BEFORE_FIRST_PITCH_SECS,
    WARMUP_POLL_SECS,
    GameState,
    _default_presence,
    _final_presence,
    _live_presence,
    _scheduled_presence,
    _warmup_presence,
    classify_game,
    delay_for,
    pick_active_game,
    remaining_linger_secs,
    seconds_until_next_morning,
    short_team_name,
)

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")


def _name(activity: discord.BaseActivity) -> str:
    """Extract .name from a BaseActivity. The stub type doesn't declare .name,
    but every concrete subclass (Game, Activity, ...) does."""
    return str(getattr(activity, "name", ""))


def _atype(activity: discord.BaseActivity) -> discord.ActivityType | None:
    """Extract .type from a BaseActivity for the same reason as _name."""
    t = getattr(activity, "type", None)
    return t if isinstance(t, discord.ActivityType) else None


# ---------------------------------------------------------------------------
# short_team_name
# ---------------------------------------------------------------------------


class TestShortTeamName:
    def test_detroit_tigers(self) -> None:
        assert short_team_name("Detroit Tigers") == "Tigers"

    def test_new_york_yankees(self) -> None:
        assert short_team_name("New York Yankees") == "Yankees"

    def test_los_angeles_angels(self) -> None:
        assert short_team_name("Los Angeles Angels") == "Angels"

    def test_los_angeles_dodgers(self) -> None:
        assert short_team_name("Los Angeles Dodgers") == "Dodgers"

    def test_st_louis(self) -> None:
        assert short_team_name("St. Louis Cardinals") == "Cardinals"

    def test_unknown_team_passes_through(self) -> None:
        assert short_team_name("Tokyo Giants") == "Tokyo Giants"

    def test_already_short_passes_through(self) -> None:
        assert short_team_name("Tigers") == "Tigers"


# ---------------------------------------------------------------------------
# pick_active_game
# ---------------------------------------------------------------------------


class TestPickActiveGame:
    def test_empty_list_returns_none(self) -> None:
        assert pick_active_game([]) is None

    def test_single_in_progress_returns_it(self) -> None:
        g = {"status": "In Progress", "id": 1}
        assert pick_active_game([g]) is g

    def test_doubleheader_skips_finished_game(self) -> None:
        g1 = {"status": "Final", "id": 1}
        g2 = {"status": "In Progress", "id": 2}
        assert pick_active_game([g1, g2]) is g2

    def test_all_final_returns_last(self) -> None:
        g1 = {"status": "Final", "id": 1}
        g2 = {"status": "Final", "id": 2}
        assert pick_active_game([g1, g2]) is g2

    def test_missing_status_key_treated_as_active(self) -> None:
        g = {"id": 1}  # no status
        assert pick_active_game([g]) is g

    def test_suspended_counted_as_final_for_picking(self) -> None:
        g1 = {"status": "Suspended", "id": 1}
        g2 = {"status": "Scheduled", "id": 2}
        assert pick_active_game([g1, g2]) is g2


# ---------------------------------------------------------------------------
# classify_game
# ---------------------------------------------------------------------------


class TestClassifyGame:
    def test_in_progress_is_live(self) -> None:
        assert classify_game({"status": "In Progress"}) == GameState.LIVE

    def test_warmup(self) -> None:
        assert classify_game({"status": "Warmup"}) == GameState.WARMUP

    def test_pre_game(self) -> None:
        assert classify_game({"status": "Pre-Game"}) == GameState.WARMUP

    def test_delayed_start_is_warmup_not_live(self) -> None:
        """'Delayed Start' contains 'Delayed' — WARMUP check must win ordering."""
        assert classify_game({"status": "Delayed Start"}) == GameState.WARMUP

    def test_delayed_mid_game_is_live(self) -> None:
        assert classify_game({"status": "Delayed"}) == GameState.LIVE

    def test_final(self) -> None:
        assert classify_game({"status": "Final"}) == GameState.POST_GAME

    def test_postponed(self) -> None:
        assert classify_game({"status": "Postponed"}) == GameState.POST_GAME

    def test_cancelled(self) -> None:
        assert classify_game({"status": "Cancelled"}) == GameState.POST_GAME

    def test_suspended(self) -> None:
        assert classify_game({"status": "Suspended"}) == GameState.POST_GAME

    def test_scheduled(self) -> None:
        assert classify_game({"status": "Scheduled"}) == GameState.SCHEDULED

    def test_preview(self) -> None:
        assert classify_game({"status": "Preview"}) == GameState.SCHEDULED

    def test_unknown_falls_back_to_scheduled(self) -> None:
        assert classify_game({"status": "Something Weird"}) == GameState.SCHEDULED

    def test_missing_status(self) -> None:
        assert classify_game({}) == GameState.SCHEDULED

    def test_scheduled_past_start_is_warmup(self) -> None:
        """MLB detailedState often lags wall clock; past-start Scheduled → WARMUP."""
        # Game was supposed to start at 11:00, now is 12:00 same day.
        game = {"status": "Scheduled", "start_time": "2024-05-15T15:00:00+00:00"}
        now = datetime(2024, 5, 15, 16, 0, tzinfo=UTC)
        assert classify_game(game, now) == GameState.WARMUP

    def test_scheduled_before_start_stays_scheduled(self) -> None:
        game = {"status": "Scheduled", "start_time": "2024-05-15T23:00:00+00:00"}
        now = datetime(2024, 5, 15, 20, 0, tzinfo=UTC)
        assert classify_game(game, now) == GameState.SCHEDULED

    def test_preview_past_start_is_warmup(self) -> None:
        game = {"status": "Preview", "start_time": "2024-05-15T15:00:00+00:00"}
        now = datetime(2024, 5, 15, 16, 0, tzinfo=UTC)
        assert classify_game(game, now) == GameState.WARMUP

    def test_malformed_start_time_falls_back_to_scheduled(self) -> None:
        game = {"status": "Scheduled", "start_time": "not-a-date"}
        now = datetime(2024, 5, 15, 16, 0, tzinfo=UTC)
        assert classify_game(game, now) == GameState.SCHEDULED


# ---------------------------------------------------------------------------
# seconds_until_next_morning
# ---------------------------------------------------------------------------


class TestSecondsUntilNextMorning:
    def test_one_hour_before_wake(self) -> None:
        now = datetime(2024, 5, 15, 9, 0, tzinfo=ET)
        assert seconds_until_next_morning(now) == pytest.approx(3600)

    def test_exactly_at_wake_flips_to_tomorrow(self) -> None:
        now = datetime(2024, 5, 15, MORNING_HOUR_LOCAL, 0, tzinfo=ET)
        assert seconds_until_next_morning(now) == pytest.approx(24 * 3600)

    def test_after_wake_sleeps_until_tomorrow(self) -> None:
        now = datetime(2024, 5, 15, 11, 0, tzinfo=ET)
        assert seconds_until_next_morning(now) == pytest.approx(23 * 3600)

    def test_late_night_et_sleeps_to_morning(self) -> None:
        now = datetime(2024, 5, 15, 23, 0, tzinfo=ET)
        assert seconds_until_next_morning(now) == pytest.approx(11 * 3600)

    def test_utc_input_converts_to_configured_tz(self) -> None:
        # 2am UTC on May 15, 2024 = 10pm ET May 14 (EDT, UTC-4).
        # Wake target at 10am ET has already passed in local terms, so target rolls to May 15 10am ET.
        # Delta = 10am ET May 15 - 10pm ET May 14 = 12 hours.
        now = datetime(2024, 5, 15, 2, 0, tzinfo=UTC)
        assert seconds_until_next_morning(now) == pytest.approx(12 * 3600)

    def test_custom_hour(self) -> None:
        now = datetime(2024, 5, 15, 5, 0, tzinfo=ET)
        assert seconds_until_next_morning(now, hour=6) == pytest.approx(3600)

    def test_explicit_tz_override(self) -> None:
        # 7am Pacific, configured to wake at 10am Pacific → 3 hours
        now = datetime(2024, 5, 15, 7, 0, tzinfo=PT)
        assert seconds_until_next_morning(now, tz=PT) == pytest.approx(3 * 3600)


# ---------------------------------------------------------------------------
# delay_for
# ---------------------------------------------------------------------------


class TestDelayFor:
    def test_live(self) -> None:
        assert delay_for(GameState.LIVE, {}, datetime.now(tz=UTC)) == LIVE_POLL_SECS

    def test_warmup(self) -> None:
        assert delay_for(GameState.WARMUP, {}, datetime.now(tz=UTC)) == WARMUP_POLL_SECS

    def test_scheduled_sleeps_until_15_min_before_start(self) -> None:
        now = datetime(2024, 5, 15, 18, 0, tzinfo=UTC)
        game = {"start_time": "2024-05-15T19:10:00Z"}
        expected = 70 * 60 - WAKE_BEFORE_FIRST_PITCH_SECS
        assert delay_for(GameState.SCHEDULED, game, now) == pytest.approx(expected)

    def test_scheduled_imminent_clamps_to_live_cadence(self) -> None:
        now = datetime(2024, 5, 15, 19, 5, tzinfo=UTC)
        game = {"start_time": "2024-05-15T19:10:00Z"}
        assert delay_for(GameState.SCHEDULED, game, now) == LIVE_POLL_SECS

    def test_scheduled_start_already_past_still_clamps(self) -> None:
        now = datetime(2024, 5, 15, 19, 30, tzinfo=UTC)
        game = {"start_time": "2024-05-15T19:10:00Z"}
        assert delay_for(GameState.SCHEDULED, game, now) == LIVE_POLL_SECS

    def test_scheduled_without_start_time_falls_through_to_morning(self) -> None:
        now = datetime(2024, 5, 15, 11, 0, tzinfo=ET)
        assert delay_for(GameState.SCHEDULED, {}, now) == pytest.approx(23 * 3600)

    def test_scheduled_with_none_game_falls_through(self) -> None:
        now = datetime(2024, 5, 15, 11, 0, tzinfo=ET)
        assert delay_for(GameState.SCHEDULED, None, now) == pytest.approx(23 * 3600)

    def test_no_game_sleeps_until_morning(self) -> None:
        now = datetime(2024, 5, 15, 11, 0, tzinfo=ET)
        assert delay_for(GameState.NO_GAME, None, now) == pytest.approx(23 * 3600)

    def test_post_game_sleeps_until_morning(self) -> None:
        now = datetime(2024, 5, 15, 23, 0, tzinfo=ET)
        assert delay_for(GameState.POST_GAME, {"status": "Final"}, now) == pytest.approx(11 * 3600)


# ---------------------------------------------------------------------------
# remaining_linger_secs
# ---------------------------------------------------------------------------


class TestRemainingLingerSecs:
    def test_just_finaled(self) -> None:
        assert remaining_linger_secs(0.0) == pytest.approx(FINAL_LINGER_SECS)

    def test_half_elapsed(self) -> None:
        assert remaining_linger_secs(FINAL_LINGER_SECS / 2) == pytest.approx(FINAL_LINGER_SECS / 2)

    def test_expired_returns_zero(self) -> None:
        assert remaining_linger_secs(FINAL_LINGER_SECS) == 0

    def test_way_past_expiry_returns_zero(self) -> None:
        assert remaining_linger_secs(FINAL_LINGER_SECS * 10) == 0


# ---------------------------------------------------------------------------
# Presence formatters
# ---------------------------------------------------------------------------


def _live_game(**overrides) -> dict:
    return {
        "game_pk": 1,
        "away_team": "New York Yankees",
        "home_team": "Detroit Tigers",
        "away_score": 2,
        "home_score": 4,
        "status": "In Progress",
        "inning": "Top 8th",
        "outs": 2,
        "start_time": "2024-05-15T19:10:00Z",
    } | overrides


class TestLivePresence:
    def test_format_has_emoji_score_inning_outs(self) -> None:
        activity, status = _live_presence(_live_game())
        assert status == discord.Status.online
        assert _name(activity) == "🔴 Yankees 2 @ Tigers 4 • Top 8th • 2 out"
        assert _atype(activity) == discord.ActivityType.watching

    def test_zero_outs(self) -> None:
        activity, _ = _live_presence(_live_game(outs=0))
        assert "0 out" in _name(activity)

    def test_uses_short_team_names(self) -> None:
        activity, _ = _live_presence(
            _live_game(away_team="St. Louis Cardinals", home_team="San Francisco Giants")
        )
        name = _name(activity)
        assert "Cardinals" in name
        assert "Giants" in name
        assert "St. Louis" not in name
        assert "San Francisco" not in name


class TestWarmupPresence:
    def test_format(self) -> None:
        activity, status = _warmup_presence(_live_game(status="Warmup"))
        assert status == discord.Status.online
        name = _name(activity)
        assert "⚾" in name
        assert "Yankees" in name
        assert "Tigers" in name


class TestScheduledPresence:
    def test_format_with_start_time(self) -> None:
        # 19:10 UTC = 3:10 PM EDT (May is EDT, UTC-4)
        activity, status = _scheduled_presence(_live_game(status="Scheduled"))
        assert status == discord.Status.idle
        name = _name(activity)
        assert "⏰" in name
        assert "3:10 pm" in name
        assert "EDT" in name

    def test_format_without_start_time(self) -> None:
        game = _live_game(status="Scheduled")
        game.pop("start_time")
        activity, _ = _scheduled_presence(game)
        assert "Upcoming" in _name(activity)


class TestFinalPresence:
    def test_format(self) -> None:
        activity, status = _final_presence(_live_game(status="Final"))
        assert status == discord.Status.idle
        name = _name(activity)
        assert "🏁" in name
        assert "FINAL" in name
        assert "Yankees 2" in name
        assert "Tigers 4" in name


class TestDefaultPresence:
    def test_returns_default_msg(self) -> None:
        activity, status = _default_presence()
        assert status == discord.Status.idle
        assert _name(activity)  # whatever PRESENCE_DEFAULT_MSG is set to


# ---------------------------------------------------------------------------
# Env var override smoke test
# ---------------------------------------------------------------------------


class TestEnvVarOverrides:
    def test_reimport_honors_custom_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Setting PRESENCE_TEAM/TZ/MSG before import yields those values at module scope."""
        monkeypatch.setenv("PRESENCE_TEAM", "nyy")
        monkeypatch.setenv("PRESENCE_TZ", "America/Los_Angeles")
        monkeypatch.setenv("PRESENCE_DEFAULT_MSG", "Yankees on deck.")

        import importlib

        import commands.presence_task as mod

        reloaded = importlib.reload(mod)
        try:
            assert reloaded.TEAM == "NYY"  # upper()-normalized
            assert str(reloaded.TZ) == "America/Los_Angeles"
            assert reloaded.DEFAULT_MSG == "Yankees on deck."
        finally:
            # Restore defaults so downstream tests see the Tigers config.
            monkeypatch.delenv("PRESENCE_TEAM", raising=False)
            monkeypatch.delenv("PRESENCE_TZ", raising=False)
            monkeypatch.delenv("PRESENCE_DEFAULT_MSG", raising=False)
            importlib.reload(mod)
