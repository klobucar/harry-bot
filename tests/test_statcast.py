"""
tests/test_statcast.py — Unit tests for the statcast.py async facade.

The data layer now sits on `bigleague` (async, polars). All bigleague calls
are mocked; no internet required. Facade functions are `async def`, so the
tests are marked `@pytest.mark.anyio` (asyncio backend) and await them.

Run with: python -m pytest tests/ -v
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import polars as pl
import pytest

from persona import harry_error
from statcast import (
    AB_EVENTS,
    HIT_EVENTS,
    compute_matchup_stats,
    resolve_player_id,
    season_range,
)

# ---------------------------------------------------------------------------
# season_range  (now returns datetime.date objects, not strings)
# ---------------------------------------------------------------------------


class TestSeasonRange:
    def test_start_date(self) -> None:
        start, _ = season_range(2023)
        assert start == datetime.date(2023, 3, 1)

    def test_end_date(self) -> None:
        _, end = season_range(2023)
        assert end == datetime.date(2023, 11, 30)

    def test_year_is_formatted(self) -> None:
        start, end = season_range(2019)
        assert start.year == 2019
        assert end.year == 2019


# ---------------------------------------------------------------------------
# resolve_player_id  (delegates to bigleague.resolve_id)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestResolvePlayerId:
    async def test_returns_none_for_no_match(self) -> None:
        with patch("bigleague.resolve_id", return_value=None):
            result = await resolve_player_id("nolan", "ryan")
        assert result is None

    async def test_returns_correct_id(self) -> None:
        with patch("bigleague.resolve_id", return_value=121250):
            result = await resolve_player_id("nolan", "ryan")
        assert result == 121250

    async def test_passes_args_in_first_last_order(self) -> None:
        """resolve_id expects (first, last) — verify the call."""
        with patch("bigleague.resolve_id", return_value=None) as mock_lookup:
            await resolve_player_id("nolan", "ryan")
        mock_lookup.assert_called_once_with("nolan", "ryan")


# ---------------------------------------------------------------------------
# AB_EVENTS / HIT_EVENTS constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_ab_events_is_frozenset(self) -> None:
        assert isinstance(AB_EVENTS, frozenset)

    def test_hit_events_subset_of_ab_events(self) -> None:
        assert HIT_EVENTS <= AB_EVENTS

    def test_strikeout_in_ab_events(self) -> None:
        assert "strikeout" in AB_EVENTS

    def test_home_run_in_hit_events(self) -> None:
        assert "home_run" in HIT_EVENTS

    def test_walk_not_in_ab_events(self) -> None:
        # walks don't count as at-bats
        assert "walk" not in AB_EVENTS


# ---------------------------------------------------------------------------
# compute_matchup_stats
# ---------------------------------------------------------------------------


def _make_matchup_df(events: list[str], pitcher_id: int = 99) -> pl.DataFrame:
    """Build a minimal batter-side Statcast-shaped polars frame for testing."""
    return pl.DataFrame({"pitcher": [pitcher_id] * len(events), "events": events})


@pytest.mark.anyio
class TestComputeMatchupStats:
    async def test_raises_on_empty_batter_data(self) -> None:
        with (
            patch("bigleague.statcast_season", return_value=pl.DataFrame()),
            pytest.raises(ValueError, match="No Statcast data"),
        ):
            await compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)

    async def test_raises_when_pitcher_never_faced_batter(self) -> None:
        df = _make_matchup_df(["single"], pitcher_id=1)
        with (
            patch("bigleague.statcast_season", return_value=df),
            pytest.raises(ValueError, match="No plate appearances"),
        ):
            await compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)

    async def test_batting_average_calculation(self) -> None:
        # 1 single + 1 strikeout = 0.500 AVG
        df = _make_matchup_df(["single", "strikeout"])
        with patch("bigleague.statcast_season", return_value=df):
            stats = await compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["batting_avg"] == pytest.approx(0.5)

    async def test_zero_avg_on_all_strikeouts(self) -> None:
        df = _make_matchup_df(["strikeout", "strikeout", "strikeout"])
        with patch("bigleague.statcast_season", return_value=df):
            stats = await compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["batting_avg"] == 0.0
        assert stats["strikeouts"] == 3

    async def test_pa_vs_ab_difference(self) -> None:
        # walks are PA but not AB; single is both
        df = _make_matchup_df(["walk", "single"])
        with patch("bigleague.statcast_season", return_value=df):
            stats = await compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["pa"] == 2
        assert stats["ab"] == 1  # walk excluded
        assert stats["hits"] == 1

    async def test_hit_count(self) -> None:
        df = _make_matchup_df(["single", "double", "triple", "home_run", "strikeout"])
        with patch("bigleague.statcast_season", return_value=df):
            stats = await compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["hits"] == 4


# ---------------------------------------------------------------------------
# persona (quick smoke test — no mocking needed)
# ---------------------------------------------------------------------------


class TestPersona:
    def test_harry_error_returns_string(self) -> None:
        msg = harry_error()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_harry_error_with_extra_contains_detail(self) -> None:
        msg = harry_error("connection refused")
        assert "connection refused" in msg
