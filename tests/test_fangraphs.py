"""
tests/test_fangraphs.py — FanGraphs facade over bigleague.

Pass-through helpers are covered with light smoke tests; the real Harry-side
logic (aggregate_career_frames' pitcher-then-batter fallback) gets focused
coverage. The data layer itself is bigleague (async, polars).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import polars as pl
import pytest

from fangraphs import (
    FangraphsBlockedError,
    aggregate_career_frames,
    fetch_leaderboard,
    fetch_player_stats,
    player_role_blocks,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_fangraphs_blocked_is_value_error() -> None:
    # Subclasses ValueError so command-layer `except ValueError` paths catch it.
    assert issubclass(FangraphsBlockedError, ValueError)


@pytest.mark.anyio
async def test_fetch_player_stats_passthrough() -> None:
    payload = {"type": "batter", "team": "DET", "stats": {"AVG": ".300"}}
    with patch("fangraphs._fg.player_stats", AsyncMock(return_value=payload)):
        out = await fetch_player_stats("Riley", "Greene", 2024)
    assert out == payload


@pytest.mark.anyio
async def test_fetch_leaderboard_passthrough() -> None:
    board = [
        {
            "rank": 1,
            "name": "Tarik Skubal",
            "team": "DET",
            "value": "2.39",
            "player_type": "pitcher",
        }
    ]
    with patch("fangraphs._fg.top_leaderboard", AsyncMock(return_value=board)) as mock:
        out = await fetch_leaderboard("ERA", 2024, "pitcher")
    assert out == board
    mock.assert_awaited_once_with("ERA", 2024, 10, "pitcher")


def test_player_role_blocks_normalizes_two_way_result() -> None:
    result = {
        "type": "two-way",
        "roles": {
            "pitcher": {"team": "LAD", "stats": {"ERA": "3.000"}},
            "batter": {"team": "LAD", "stats": {"OPS": "1.000"}},
        },
    }
    assert set(player_role_blocks(result)) == {"pitcher", "batter"}


class TestAggregateCareerFrames:
    def _pitcher_frame(self, year: int) -> pl.DataFrame:
        return pl.DataFrame(
            [
                {
                    "Name": "Tarik Skubal",
                    "_year": year,
                    "W": 18,
                    "L": 4,
                    "IP": 192.0,
                    "ERA": 2.39,
                    "WAR": 6.0,
                }
            ]
        )

    def _batter_frame(self, year: int) -> pl.DataFrame:
        return pl.DataFrame(
            [{"Name": "Riley Greene", "_year": year, "PA": 600, "HR": 24, "AVG": 0.262, "WAR": 4.0}]
        )

    def test_prefers_pitcher(self) -> None:
        result = aggregate_career_frames(
            [self._pitcher_frame(2023), self._pitcher_frame(2024)],
            [],
            "Tarik",
            "Skubal",
            [2023, 2024],
        )
        assert result["type"] == "pitcher"
        assert result["stats"]["Seasons"] == "2"
        assert "Career (2023-2024)" in result["team"]

    def test_falls_back_to_batter(self) -> None:
        result = aggregate_career_frames(
            [],
            [self._batter_frame(2024)],
            "Riley",
            "Greene",
            [2024, 2024],
        )
        assert result["type"] == "batter"

    def test_returns_both_roles_for_two_way_player(self) -> None:
        result = aggregate_career_frames(
            [self._pitcher_frame(2024)],
            [
                pl.DataFrame(
                    [{"Name": "Tarik Skubal", "_year": 2024, "PA": 10, "HR": 1, "WAR": 0.1}]
                )
            ],
            "Tarik",
            "Skubal",
            [2024],
        )
        assert result["type"] == "two-way"
        assert set(result["roles"]) == {"pitcher", "batter"}

    def test_no_frames_raises(self) -> None:
        with pytest.raises(ValueError, match="No FanGraphs data"):
            aggregate_career_frames([], [], "No", "Body", [2024, 2024])
