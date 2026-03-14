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
                "person": {"fullName": "Spencer Torkelson"},
                "position": {"abbreviation": "1B"},
                "note": "Right hand (10-day)",
            },
        ]
    }

    def test_returns_il_players(self) -> None:
        with patch("mlb_api.requests.get", return_value=_mock_get(self._PAYLOAD)):
            result = fetch_injuries("DET")
        assert len(result) == 1
        assert result[0]["name"] == "Spencer Torkelson"
        assert "hand" in result[0]["note"]

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
