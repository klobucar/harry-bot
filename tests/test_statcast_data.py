"""
tests/test_statcast_data.py — statcast_stats facade helpers whose reshaping
logic lives in Harry (not just a bigleague pass-through): pitch arsenal,
standings table formatting, and schedule block formatting.

The data layer is bigleague (async, polars); we patch at the bigleague
boundary and await the facade.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from statcast import fetch_pitch_arsenal, fetch_schedule, fetch_standings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _savant_csv(arsenal_type: str, rows: list[tuple[int, str, str]]) -> SimpleNamespace:
    """A fake Savant response for the wide pitch-arsenals board (FF + SL only)."""
    cols = {
        "avg_speed": ("ff_avg_speed", "sl_avg_speed"),
        "avg_spin": ("ff_avg_spin", "sl_avg_spin"),
        "n_": ("n_ff", "n_sl"),
    }[arsenal_type]
    lines = [f'"last_name, first_name",pitcher,{cols[0]},{cols[1]}']
    lines += [f'"Doe, John",{pid},{ff},{sl}' for pid, ff, sl in rows]
    return SimpleNamespace(content="\n".join(lines).encode())


def _fake_savant(boards: dict[str, list[tuple[int, str, str]]]) -> AsyncMock:
    async def _get(_url: str, params: dict[str, str]) -> SimpleNamespace:
        return _savant_csv(params["type"], boards[params["type"]])

    return AsyncMock(side_effect=_get)


@pytest.mark.anyio
class TestFetchPitchArsenal:
    async def test_merges_boards_and_sorts_by_usage(self) -> None:
        boards = {
            "avg_speed": [(999, "90.0", "80.0"), (123456, "86.4", "95.1")],
            "avg_spin": [(999, "2000", "2100"), (123456, "2500", "2300")],
            # Rounded shares that don't sum to 100 -> renormalised.
            "n_": [(999, "50.0", "50.0"), (123456, "30.0", "45.0")],
        }
        with patch("statcast_stats.savant_get", _fake_savant(boards)) as mock:
            out = await fetch_pitch_arsenal(123456, 2024)

        assert mock.await_count == 3
        assert [p["pitch"] for p in out] == ["SL", "FF"]  # sorted by usage desc
        assert set(out[0]) == {"pitch", "mph", "spin", "usage"}
        assert out[0]["usage"] == pytest.approx(60.0)
        assert out[1]["usage"] == pytest.approx(40.0)
        assert out[0]["mph"] == pytest.approx(95.1)
        assert out[0]["spin"] == pytest.approx(2300.0)

    async def test_skips_pitches_the_pitcher_does_not_throw(self) -> None:
        boards = {
            "avg_speed": [(123456, "95.1", "")],
            "avg_spin": [(123456, "2300", "")],
            "n_": [(123456, "100.0", "")],
        }
        with patch("statcast_stats.savant_get", _fake_savant(boards)):
            out = await fetch_pitch_arsenal(123456, 2024)

        assert [p["pitch"] for p in out] == ["FF"]
        assert out[0]["usage"] == pytest.approx(100.0)

    async def test_missing_pitcher_raises(self) -> None:
        boards = {
            "avg_speed": [(999, "90.0", "80.0")],
            "avg_spin": [(999, "2000", "2100")],
            "n_": [(999, "50.0", "50.0")],
        }
        with (
            patch("statcast_stats.savant_get", _fake_savant(boards)),
            pytest.raises(ValueError, match="No arsenal data"),
        ):
            await fetch_pitch_arsenal(123456, 2024)

    async def test_empty_response_raises(self) -> None:
        empty = AsyncMock(return_value=SimpleNamespace(content=b""))
        with (
            patch("statcast_stats.savant_get", empty),
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
