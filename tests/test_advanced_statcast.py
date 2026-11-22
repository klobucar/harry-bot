"""
tests/test_advanced_statcast.py — Tests for the advanced statcast helpers.

The data layer now sits on `bigleague` (async, polars). All bigleague
network calls are mocked; facade functions are awaited.
"""

from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

from statcast import fetch_exit_velo, fetch_hot_cold, fetch_percentile_ranks

# ---------------------------------------------------------------------------
# fetch_exit_velo
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestFetchExitVelo:
    def _make_evdf(self, player_id: int) -> pl.DataFrame:
        return pl.DataFrame(
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

    async def test_returns_exit_velo_dict(self) -> None:
        df = self._make_evdf(player_id=111)
        with patch("bigleague.batter_exit_velo", return_value=df):
            result = await fetch_exit_velo(111, 2024, "Riley Greene")
        assert "Avg Exit Velo" in result
        assert "92.3" in str(result["Avg Exit Velo"])

    async def test_player_not_in_leaderboard_raises(self) -> None:
        df = self._make_evdf(player_id=999)
        with (
            patch("bigleague.batter_exit_velo", return_value=df),
            pytest.raises(ValueError, match="No exit velocity data"),
        ):
            await fetch_exit_velo(111, 2024, "Riley Greene")

    async def test_empty_df_raises(self) -> None:
        empty = pl.DataFrame(schema={"player_id": pl.Int64})
        with (
            patch("bigleague.batter_exit_velo", return_value=empty),
            pytest.raises(ValueError, match="No exit velocity data"),
        ):
            await fetch_exit_velo(111, 2024, "Riley Greene")


# ---------------------------------------------------------------------------
# fetch_hot_cold (batter / pitcher)  # noqa: ERA001
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestFetchHotCold:
    def _make_statcast_df(self) -> pl.DataFrame:
        return pl.DataFrame(
            [
                {"events": "single", "type": "X"},
                {"events": "home_run", "type": "X"},
                {"events": "strikeout", "type": "S"},
                {"events": "walk", "type": "B"},
                {"events": "field_out", "type": "X"},
            ]
        )

    async def test_batter_returns_avg_obp_slg(self) -> None:
        df = self._make_statcast_df()
        with patch("bigleague.statcast_batter", return_value=df):
            result = await fetch_hot_cold(111, 14, "Riley Greene", player_type="batter")
        assert "AVG" in result
        assert "OBP" in result
        assert "SLG" in result

    async def test_pitcher_returns_pitch_counts(self) -> None:
        df = self._make_statcast_df()
        with patch("bigleague.statcast_pitcher", return_value=df):
            result = await fetch_hot_cold(111, 14, "Tarik Skubal", player_type="pitcher")
        assert "Pitches" in result
        assert "K" in result

    async def test_empty_data_raises(self) -> None:
        with (
            patch("bigleague.statcast_batter", return_value=pl.DataFrame()),
            pytest.raises(ValueError, match="No Statcast data"),
        ):
            await fetch_hot_cold(111, 14, "Riley Greene", player_type="batter")


# ---------------------------------------------------------------------------
# fetch_percentile_ranks
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestFetchPercentileRanks:
    def _make_rank_df(self, player_id_col: str, player_id: int) -> pl.DataFrame:
        return pl.DataFrame(
            [
                {
                    player_id_col: player_id,
                    "k_percent": 95,
                    "xwoba": 88,
                    "xera": 99,
                }
            ]
        )

    async def test_pitcher_percentiles_returned(self) -> None:
        df = self._make_rank_df("player_id", 111)
        with patch("bigleague.pitcher_percentile_ranks", return_value=df):
            result = await fetch_percentile_ranks(111, 2024, "Tarik Skubal", "pitcher")
        assert "K%" in result
        assert "95 th percentile" in result["K%"]

    async def test_player_not_found_raises(self) -> None:
        df = self._make_rank_df("player_id", 999)
        with (
            patch("bigleague.pitcher_percentile_ranks", return_value=df),
            pytest.raises(ValueError, match="No percentile data found"),
        ):
            await fetch_percentile_ranks(111, 2024, "Tarik Skubal", "pitcher")

    async def test_empty_data_raises(self) -> None:
        with (
            patch("bigleague.pitcher_percentile_ranks", return_value=pl.DataFrame()),
            pytest.raises(ValueError, match="No percentile data found"),
        ):
            await fetch_percentile_ranks(111, 2024, "Tarik Skubal", "pitcher")
