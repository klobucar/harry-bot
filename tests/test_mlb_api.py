"""
tests/test_mlb_api.py — Tests for mlb_api.py helpers.

All network calls (urllib.request.urlopen) are mocked.
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from mlb_api import (
    _team_id,
    fetch_injuries,
    fetch_live_scores,
    fetch_next_game,
    fetch_recent_results,
    fetch_roster,
    fetch_transactions,
)

# ---------------------------------------------------------------------------
# Helper: mock requests.get to return a JSON payload
# ---------------------------------------------------------------------------


def _mock_get(payload: dict):
    """Return a mock requests.Response that returns the given payload as JSON."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ---------------------------------------------------------------------------
# _team_id
# ---------------------------------------------------------------------------


class TestTeamId:
    def test_known_abbreviation(self) -> None:
        assert _team_id("DET") == 116

    def test_case_insensitive(self) -> None:
        assert _team_id("det") == 116

    def test_alias_kcr(self) -> None:
        assert _team_id("KCR") == _team_id("KC")

    def test_unknown_abbreviation_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown team"):
            _team_id("XYZ")


# ---------------------------------------------------------------------------
# fetch_roster
# ---------------------------------------------------------------------------


class TestFetchRoster:
    _PAYLOAD: ClassVar[dict] = {
        "roster": [
            {
                "person": {"fullName": "Tarik Skubal"},
                "position": {"abbreviation": "SP"},
                "status": {"description": "Active"},
            },
            {
                "person": {"fullName": "Riley Greene"},
                "position": {"abbreviation": "OF"},
                "status": {"description": "Active"},
            },
        ]
    }

    def test_returns_list_of_players(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_roster("DET")
        assert len(result) == 2
        names = [p["name"] for p in result]
        assert "Tarik Skubal" in names

    def test_player_has_required_keys(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_roster("DET")
        for p in result:
            assert "name" in p
            assert "pos" in p

    def test_empty_roster_raises(self) -> None:
        with (
            patch("mlb_api.requests.get", return_value=_mock_get({"roster": []})),
            pytest.raises(ValueError, match="No active roster"),
        ):
            fetch_roster("DET")

    def test_unknown_team_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown team"):
            fetch_roster("ZZZ")


# ---------------------------------------------------------------------------
# fetch_injuries
# ---------------------------------------------------------------------------


class TestFetchInjuries:
    _PAYLOAD: ClassVar[dict] = {
        "roster": [
            {
                "person": {"fullName": "Justin Verlander"},
                "position": {"abbreviation": "P"},
                "status": {"code": "D15", "description": "Injured 15-Day"},
                "note": "Left hip inflammation.",
            },
            {
                "person": {"fullName": "Tarik Skubal"},
                "position": {"abbreviation": "P"},
                "status": {"code": "A", "description": "Active"},
                "note": "",
            },
            {
                "person": {"fullName": "Troy Melton"},
                "position": {"abbreviation": "P"},
                "status": {"code": "D60", "description": "Injured 60-Day"},
                "note": "",
            },
        ]
    }

    def test_returns_only_il_players(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_injuries("DET")
        names = [p["name"] for p in result]
        assert "Justin Verlander" in names
        assert "Troy Melton" in names
        assert "Tarik Skubal" not in names

    def test_note_includes_il_stint(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_injuries("DET")
        verlander = next(p for p in result if p["name"] == "Justin Verlander")
        assert "15-Day IL" in verlander["note"]
        assert "hip" in verlander["note"]
        melton = next(p for p in result if p["name"] == "Troy Melton")
        assert melton["note"] == "60-Day IL"

    def test_empty_il_returns_empty_list(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get({"roster": []})):
            result = fetch_injuries("DET")
        assert result == []


# ---------------------------------------------------------------------------
# fetch_transactions
# ---------------------------------------------------------------------------


class TestFetchTransactions:
    _PAYLOAD: ClassVar[dict] = {
        "transactions": [
            {"date": "2025-04-01", "description": "Tarik Skubal placed on 15-day IL"},
            {"date": "2025-03-30", "description": "Riley Greene activated from IL"},
        ]
    }

    def test_returns_sorted_desc_by_date(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_transactions("DET", days=7)
        assert result[0]["date"] == "2025-04-01"

    def test_description_present(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_transactions("DET")
        assert all("desc" in t for t in result)

    def test_empty_transactions_raises(self) -> None:
        with (
            patch("mlb_api.requests.get", return_value=_mock_get({"transactions": []})),
            pytest.raises(ValueError, match="No transactions"),
        ):
            fetch_transactions("DET", days=7)


# ---------------------------------------------------------------------------
# fetch_live_scores
# ---------------------------------------------------------------------------


class TestFetchLiveScores:
    _PAYLOAD: ClassVar[dict] = {
        "dates": [
            {
                "games": [
                    {
                        "status": {"detailedState": "In Progress"},
                        "teams": {
                            "home": {"team": {"name": "Detroit Tigers"}, "score": 3},
                            "away": {"team": {"name": "Cleveland Guardians"}, "score": 2},
                        },
                        "linescore": {
                            "currentInningOrdinal": "7th",
                            "inningHalf": "Bottom",
                            "outs": 2,
                        },
                    }
                ]
            }
        ]
    }

    def test_returns_game_data(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_live_scores("DET")
        assert len(result) == 1
        assert result[0]["home_team"] == "Detroit Tigers"
        assert result[0]["home_score"] == 3

    def test_no_game_today_raises(self) -> None:
        with (
            patch("mlb_api.requests.get", return_value=_mock_get({"dates": []})),
            pytest.raises(ValueError, match="no game today"),
        ):
            fetch_live_scores("DET")


# ---------------------------------------------------------------------------
# fetch_next_game
# ---------------------------------------------------------------------------


class TestFetchNextGame:
    _PAYLOAD: ClassVar[dict] = {
        "dates": [
            {
                "date": "2025-04-05",
                "games": [
                    {
                        "status": {"abstractGameState": "Preview"},
                        "gameDate": "2025-04-05T18:10:00Z",
                        "teams": {
                            "home": {
                                "team": {"name": "Detroit Tigers"},
                                "probablePitcher": {"fullName": "Tarik Skubal"},
                            },
                            "away": {
                                "team": {"name": "Cleveland Guardians"},
                                "probablePitcher": {"fullName": "Shane Bieber"},
                            },
                        },
                    }
                ],
            }
        ]
    }

    def test_returns_next_game(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_next_game("DET")
        assert result["home_team"] == "Detroit Tigers"
        assert result["home_probable"] == "Tarik Skubal"
        assert result["date"] == "2025-04-05"

    def test_no_upcoming_game_raises(self) -> None:
        with (
            patch("mlb_api.requests.get", return_value=_mock_get({"dates": []})),
            pytest.raises(ValueError, match="No upcoming games"),
        ):
            fetch_next_game("DET")


# ---------------------------------------------------------------------------
# fetch_recent_results
# ---------------------------------------------------------------------------


def _game(date_str, home_id, home_score, away_id, away_score, *, status="Final", detailed="Final"):
    """Build a minimal MLB Stats API game payload for the schedule endpoint."""
    home_winner = home_score > away_score
    return {
        "status": {"abstractGameState": status, "detailedState": detailed},
        "teams": {
            "home": {
                "team": {"id": home_id, "abbreviation": "HHH"},
                "score": home_score,
                "isWinner": home_winner,
            },
            "away": {
                "team": {"id": away_id, "abbreviation": "AAA"},
                "score": away_score,
                "isWinner": not home_winner,
            },
        },
    }


class TestFetchRecentResults:
    """116 = DET. Build a few schedule days, confirm we extract H/A + W/L correctly."""

    def test_oldest_to_newest_order_with_home_away_split(self) -> None:
        payload = {
            "dates": [
                {"date": "2026-04-30", "games": [_game("2026-04-30", 116, 5, 999, 2)]},
                {"date": "2026-05-01", "games": [_game("2026-05-01", 999, 3, 116, 1)]},
                {"date": "2026-05-02", "games": [_game("2026-05-02", 116, 2, 999, 4)]},
            ]
        }
        with patch("mlb_api.requests.get", return_value=_mock_get(payload)):
            results = fetch_recent_results("DET", n=10)

        assert [r["date"] for r in results] == ["2026-04-30", "2026-05-01", "2026-05-02"]
        assert [r["is_home"] for r in results] == [True, False, True]
        assert [r["result"] for r in results] == ["W", "L", "L"]

    def test_postponed_games_marked_p_and_kept(self) -> None:
        payload = {
            "dates": [
                {
                    "date": "2026-05-03",
                    "games": [
                        _game(
                            "2026-05-03",
                            116,
                            0,
                            999,
                            0,
                            status="Preview",
                            detailed="Postponed",
                        )
                    ],
                }
            ]
        }
        with patch("mlb_api.requests.get", return_value=_mock_get(payload)):
            results = fetch_recent_results("DET")
        assert len(results) == 1
        assert results[0]["result"] == "P"

    def test_in_progress_games_skipped(self) -> None:
        payload = {
            "dates": [
                {
                    "date": "2026-05-04",
                    "games": [
                        _game(
                            "2026-05-04",
                            116,
                            1,
                            999,
                            0,
                            status="Live",
                            detailed="In Progress",
                        )
                    ],
                }
            ]
        }
        with patch("mlb_api.requests.get", return_value=_mock_get(payload)):
            assert fetch_recent_results("DET") == []

    def test_n_caps_results_keeping_newest(self) -> None:
        days = [
            {"date": f"2026-04-{i:02d}", "games": [_game(f"2026-04-{i:02d}", 116, i, 999, 0)]}
            for i in range(1, 13)
        ]
        with patch("mlb_api.requests.get", return_value=_mock_get({"dates": days})):
            results = fetch_recent_results("DET", n=5)
        assert len(results) == 5
        assert results[0]["date"] == "2026-04-08"
        assert results[-1]["date"] == "2026-04-12"
