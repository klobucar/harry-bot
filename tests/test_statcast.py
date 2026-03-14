"""
tests/test_statcast.py — Unit tests for statcast.py pure helpers.

All pybaseball network calls are mocked. No internet required.
Run with: python -m pytest tests/ -v
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
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
# season_range
# ---------------------------------------------------------------------------


class TestSeasonRange:
    def test_start_date(self) -> None:
        start, _ = season_range(2023)
        assert start == "2023-03-01"

    def test_end_date(self) -> None:
        _, end = season_range(2023)
        assert end == "2023-11-30"

    def test_year_is_formatted(self) -> None:
        start, end = season_range(2019)
        assert start.startswith("2019")
        assert end.startswith("2019")


# ---------------------------------------------------------------------------
# resolve_player_id
# ---------------------------------------------------------------------------


class TestResolvePlayerId:
    def test_returns_none_for_empty_result(self) -> None:
        with patch("statcast.playerid_lookup", return_value=pd.DataFrame()):
            result = resolve_player_id("nolan", "ryan")
        assert result is None

    def test_returns_none_when_no_mlbam_column(self) -> None:
        df = pd.DataFrame({"key_mlbam": [None, None]})
        with patch("statcast.playerid_lookup", return_value=df):
            result = resolve_player_id("nolan", "ryan")
        assert result is None

    def test_returns_correct_id(self) -> None:
        df = pd.DataFrame({"key_mlbam": [121250]})
        with patch("statcast.playerid_lookup", return_value=df):
            result = resolve_player_id("nolan", "ryan")
        assert result == 121250

    def test_returns_first_match_on_multiple_rows(self) -> None:
        df = pd.DataFrame({"key_mlbam": [111, 222, 333]})
        with patch("statcast.playerid_lookup", return_value=df):
            result = resolve_player_id("pedro", "martinez")
        assert result == 111

    def test_passes_args_in_correct_order(self) -> None:
        """playerid_lookup expects (last, first, fuzzy=True) — verify the call."""
        with patch("statcast.playerid_lookup", return_value=pd.DataFrame()) as mock_lookup:
            resolve_player_id("nolan", "ryan")
        mock_lookup.assert_called_once_with("ryan", "nolan", fuzzy=True)


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


def _make_matchup_df(events: list[str], pitcher_id: int = 99) -> pd.DataFrame:
    """Build a minimal StatCast-shaped DataFrame for testing."""
    return pd.DataFrame({"pitcher": [pitcher_id] * len(events), "events": events})


class TestComputeMatchupStats:
    def test_raises_on_empty_batter_data(self) -> None:
        with (
            patch("statcast.statcast_batter", return_value=pd.DataFrame()),
            pytest.raises(ValueError, match="No Statcast data"),
        ):
            compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)

    def test_raises_when_pitcher_never_faced_batter(self) -> None:
        df = _make_matchup_df(["single"], pitcher_id=1)
        with (
            patch("statcast.statcast_batter", return_value=df),
            pytest.raises(ValueError, match="No plate appearances"),
        ):
            compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)

    def test_batting_average_calculation(self) -> None:
        # 1 single + 1 strikeout = 0.500 AVG
        df = _make_matchup_df(["single", "strikeout"])
        with patch("statcast.statcast_batter", return_value=df):
            stats = compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["batting_avg"] == pytest.approx(0.5)

    def test_zero_avg_on_all_strikeouts(self) -> None:
        df = _make_matchup_df(["strikeout", "strikeout", "strikeout"])
        with patch("statcast.statcast_batter", return_value=df):
            stats = compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["batting_avg"] == 0.0
        assert stats["strikeouts"] == 3

    def test_pa_vs_ab_difference(self) -> None:
        # walks are PA but not AB; single is both
        df = _make_matchup_df(["walk", "single"])
        with patch("statcast.statcast_batter", return_value=df):
            stats = compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["pa"] == 2
        assert stats["ab"] == 1  # walk excluded
        assert stats["hits"] == 1

    def test_hit_count(self) -> None:
        df = _make_matchup_df(["single", "double", "triple", "home_run", "strikeout"])
        with patch("statcast.statcast_batter", return_value=df):
            stats = compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
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
