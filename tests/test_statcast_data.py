"""
tests/test_statcast_data.py — statcast_stats facade helpers whose reshaping
logic lives in Harry (not just a bigleague pass-through): pitch arsenal,
standings table formatting, and schedule block formatting.

The data layer is bigleague (async, polars); we patch at the bigleague
boundary and await the facade.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import polars as pl
import pytest

from statcast import fetch_pitch_arsenal, fetch_schedule, fetch_standings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
class TestFetchPitchArsenal:
    async def test_remaps_usage_and_sorts(self) -> None:
        frame = pl.DataFrame(
            [
                {"pitch_type": "FF", "avg_speed": 95.1, "avg_spin": 2300.0, "pitches": 600},
                {"pitch_type": "SL", "avg_speed": 86.4, "avg_spin": 2500.0, "pitches": 400},
            ]
        )
        with patch("bigleague.pitcher_pitch_arsenal", AsyncMock(return_value=frame)):
            out = await fetch_pitch_arsenal(123456, 2024)

        assert [p["pitch"] for p in out] == ["FF", "SL"]  # sorted by usage desc
        # usage % computed from the 600/400 split, exposed under the `usage` key.
        assert set(out[0]) == {"pitch", "mph", "spin", "usage"}
        assert out[0]["usage"] == pytest.approx(60.0)
        assert out[1]["usage"] == pytest.approx(40.0)
        assert out[0]["mph"] == pytest.approx(95.1)

    async def test_empty_raises(self) -> None:
        with (
            patch("bigleague.pitcher_pitch_arsenal", AsyncMock(return_value=pl.DataFrame())),
            pytest.raises(ValueError, match="No arsenal data"),
        ):
            await fetch_pitch_arsenal(123456, 2024)


@pytest.mark.anyio
class TestFetchStandings:
    async def test_formats_division_tables(self) -> None:
        divisions = [
            {
                "division": "AL Central",
                "teams": [
                    {"name": "Tigers", "w": 90, "l": 72, "gb": "-", "pct": ".556"},
                    {"name": "Guardians", "w": 88, "l": 74, "gb": "2.0", "pct": ".543"},
                ],
            }
        ]
        with patch("bigleague.standings", AsyncMock(return_value=divisions)):
            out = await fetch_standings(2024)

        assert len(out) == 1
        name, table = out[0]
        assert name == "AL Central"
        assert "Tigers" in table
        assert "Guardians" in table
        assert table.startswith("```")
        assert table.endswith("```")
        assert "90-72" in table

    async def test_empty_raises(self) -> None:
        with (
            patch("bigleague.standings", AsyncMock(return_value=[])),
            pytest.raises(ValueError, match="No standings data"),
        ):
            await fetch_standings(2024)


def _schedule_payload() -> dict:
    # DET (team id 116) — one completed home win, one upcoming away game.
    return {
        "dates": [
            {
                "date": "2024-04-01",
                "games": [
                    {
                        "gameDate": "2024-04-01T17:10:00Z",
                        "status": {"abstractGameState": "Final"},
                        "teams": {
                            "home": {
                                "team": {"id": 116, "name": "Tigers"},
                                "score": 5,
                                "isWinner": True,
                            },
                            "away": {
                                "team": {"id": 118, "name": "Royals"},
                                "score": 3,
                                "isWinner": False,
                            },
                        },
                    }
                ],
            },
            {
                "date": "2024-04-05",
                "games": [
                    {
                        "gameDate": "2024-04-05T23:40:00Z",
                        "status": {"abstractGameState": "Preview"},
                        "teams": {
                            "home": {"team": {"id": 147, "name": "Yankees"}},
                            "away": {"team": {"id": 116, "name": "Tigers"}},
                        },
                    }
                ],
            },
        ]
    }


@pytest.mark.anyio
class TestFetchSchedule:
    async def test_past_and_upcoming_blocks(self) -> None:
        with patch("statcast_stats.mlb_get", AsyncMock(return_value=_schedule_payload())):
            past, upcoming = await fetch_schedule("DET", 2024)

        # Completed: home vs KC, win 5-3.
        for token in ("vs", "KC", "W", "5-3"):
            assert token in past
        # Upcoming: away @ NYY.
        assert "@" in upcoming
        assert "NYY" in upcoming

    async def test_no_games_raises(self) -> None:
        with (
            patch("statcast_stats.mlb_get", AsyncMock(return_value={"dates": []})),
            pytest.raises(ValueError, match="No schedule data"),
        ):
            await fetch_schedule("DET", 2024)

    async def test_unknown_team_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown team"):
            await fetch_schedule("ZZZ", 2024)
