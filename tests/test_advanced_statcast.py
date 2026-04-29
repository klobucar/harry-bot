"""
tests/test_advanced_statcast.py — Tests for the advanced statcast helpers.

All pybaseball network calls are mocked.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from fangraphs import fetch_career_stats, fetch_leaderboard
from statcast import fetch_exit_velo, fetch_hot_cold, fetch_percentile_ranks


def _fg_side(pit: pd.DataFrame | None = None, bat: pd.DataFrame | None = None):
    """Build a side_effect for patch('fangraphs.fetch_fg_leaderboard')."""
    pit_df = pit if pit is not None else pd.DataFrame()
    bat_df = bat if bat is not None else pd.DataFrame()
    return lambda _year, kind, **_kw: pit_df if kind == "pit" else bat_df


# ---------------------------------------------------------------------------
# fetch_exit_velo
# ---------------------------------------------------------------------------


class TestFetchExitVelo:
    def _make_evdf(self, player_id: int) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "player_id": player_id,
                    "avg_hit_speed": 92.3,
                    "max_hit_speed": 112.4,
                    "avg_hit_angle": 15.2,
                    "brl_percent": 14.5,
                    "anglesweetspotpercent": 48.2,
                    "brl_pa": 18,
                    "pa": 420,
                }
            ]
        )

    def test_returns_exit_velo_dict(self) -> None:
        df = self._make_evdf(player_id=111)
        with patch("statcast_patch.statcast_batter_exitvelo_barrels", return_value=df):
            result = fetch_exit_velo(111, 2024, "Riley Greene")
        assert "Avg Exit Velo" in result
        assert "92.3" in str(result["Avg Exit Velo"])

    def test_player_not_in_leaderboard_raises(self) -> None:
        df = self._make_evdf(player_id=999)
        with (
            patch("statcast_patch.statcast_batter_exitvelo_barrels", return_value=df),
            pytest.raises(ValueError, match="No exit velocity data"),
        ):
            fetch_exit_velo(111, 2024, "Riley Greene")

    def test_empty_df_raises(self) -> None:
        with (
            patch("statcast_patch.statcast_batter_exitvelo_barrels", return_value=pd.DataFrame()),
            pytest.raises(ValueError, match="No exit velocity data available"),
        ):
            fetch_exit_velo(111, 2024, "Riley Greene")


# ---------------------------------------------------------------------------
# fetch_hot_cold (batter)  # noqa: ERA001
# ---------------------------------------------------------------------------


class TestFetchHotCold:
    def _make_statcast_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"events": "single", "type": "X"},
                {"events": "home_run", "type": "X"},
                {"events": "strikeout", "type": "S"},
                {"events": "walk", "type": "B"},
                {"events": "field_out", "type": "X"},
            ]
        )

    def test_batter_returns_avg_obp_slg(self) -> None:
        df = self._make_statcast_df()
        with patch("statcast_patch.statcast_batter", return_value=df):
            result = fetch_hot_cold(111, 14, "Riley Greene", player_type="batter")
        assert "AVG" in result
        assert "OBP" in result
        assert "SLG" in result

    def test_pitcher_returns_pitch_counts(self) -> None:
        df = self._make_statcast_df()
        with patch("statcast_patch.statcast_pitcher", return_value=df):
            result = fetch_hot_cold(111, 14, "Tarik Skubal", player_type="pitcher")
        assert "Pitches" in result
        assert "K" in result

    def test_empty_data_raises(self) -> None:
        with (
            patch("statcast_patch.statcast_batter", return_value=pd.DataFrame()),
            pytest.raises(ValueError, match="No Statcast data"),
        ):
            fetch_hot_cold(111, 14, "Riley Greene", player_type="batter")


# ---------------------------------------------------------------------------
# fetch_percentile_ranks
# ---------------------------------------------------------------------------


class TestFetchPercentileRanks:
    def _make_rank_df(self, player_id_col: str, player_id: int) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    player_id_col: player_id,
                    "k_percent": 95,
                    "xwoba": 88,
                    "xera": 99,
                }
            ]
        )

    def test_pitcher_percentiles_returned(self) -> None:
        df = self._make_rank_df("player_id", 111)
        with patch("statcast_patch.statcast_pitcher_percentile_ranks", return_value=df):
            result = fetch_percentile_ranks(111, 2024, "Tarik Skubal", "pitcher")
        assert "K%" in result
        assert "95th percentile" in result["K%"]

    def test_player_not_found_raises(self) -> None:
        df = self._make_rank_df("player_id", 999)
        with (
            patch("statcast_patch.statcast_pitcher_percentile_ranks", return_value=df),
            pytest.raises(ValueError, match="No percentile data found"),
        ):
            fetch_percentile_ranks(111, 2024, "Tarik Skubal", "pitcher")

    def test_empty_data_raises(self) -> None:
        with (
            patch("statcast_patch.statcast_pitcher_percentile_ranks", return_value=pd.DataFrame()),
            pytest.raises(ValueError, match="No percentile rank data"),
        ):
            fetch_percentile_ranks(111, 2024, "Tarik Skubal", "pitcher")


# ---------------------------------------------------------------------------
# fetch_career_stats
# ---------------------------------------------------------------------------


class TestFetchCareerStats:
    def _make_pitch_df(self, name: str = "tarik skubal") -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Name": name,
                    "Team": "DET",
                    "ERA": 2.99,
                    "FIP": 3.10,
                    "WAR": 8.2,
                    "IP": 194.0,
                    "W": 18,
                    "L": 4,
                    "WHIP": 0.93,
                }
            ]
        )

    def _make_bat_df(self, name: str = "riley greene") -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Name": name,
                    "Team": "DET",
                    "AVG": 0.287,
                    "OBP": 0.360,
                    "SLG": 0.510,
                    "WAR": 5.1,
                    "HR": 25,
                    "RBI": 88,
                    "PA": 620,
                }
            ]
        )

    def test_finds_pitcher(self) -> None:
        df = self._make_pitch_df("tarik skubal")
        with patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side(pit=df)):
            result = fetch_career_stats("tarik", "skubal")
        assert result["type"] == "pitcher"
        assert "ERA" in result["stats"]

    def test_falls_back_to_batter(self) -> None:
        bat_df = self._make_bat_df("riley greene")
        with patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side(bat=bat_df)):
            result = fetch_career_stats("riley", "greene")
        assert result["type"] == "batter"

    def test_not_found_raises(self) -> None:
        with (
            patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side()),
            pytest.raises(ValueError, match="No FanGraphs career data"),
        ):
            fetch_career_stats("nobody", "here")


# ---------------------------------------------------------------------------
# fetch_leaderboard
# ---------------------------------------------------------------------------


class TestFetchLeaderboard:
    def _make_pitch_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            [{"Name": f"Pitcher {i}", "Team": "DET", "ERA": float(i) * 0.3} for i in range(1, 15)]
        )

    def test_returns_top_10(self) -> None:
        df = self._make_pitch_df()
        with patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side(pit=df)):
            result = fetch_leaderboard("ERA", 2024, "pitcher")
        assert len(result) == 10

    def test_rank_starts_at_1(self) -> None:
        df = self._make_pitch_df()
        with patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side(pit=df)):
            result = fetch_leaderboard("ERA", 2024, "pitcher")
        assert result[0]["rank"] == 1

    def test_unknown_stat_raises(self) -> None:
        with (
            patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side()),
            pytest.raises(ValueError, match="not found"),
        ):
            fetch_leaderboard("NONEXISTENT_STAT", 2024, "auto")
