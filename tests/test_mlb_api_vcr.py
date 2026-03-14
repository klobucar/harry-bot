"""
tests/test_mlb_api_vcr.py — VCR-based integration tests for mlb_api.py.

These tests replay recorded HTTP cassettes (tests/cassettes/*.yaml) so they
never hit the real MLB Stats API during CI.

To re-record cassettes against the live API:
    uv run pytest tests/test_mlb_api_vcr.py --record-mode all

To run in offline/replay mode (default):
    uv run pytest tests/test_mlb_api_vcr.py
"""

from __future__ import annotations

import pytest

from mlb_api import (
    fetch_injuries,
    fetch_live_scores,
    fetch_next_game,
    fetch_roster,
    fetch_transactions,
)


@pytest.mark.vcr
def test_fetch_roster_returns_players() -> None:
    """Roster endpoint returns a non-empty list with expected fields."""
    result = fetch_roster("DET")
    assert isinstance(result, list)
    assert len(result) > 0
    for player in result:
        assert "name" in player
        assert "pos" in player
        assert isinstance(player["name"], str)


@pytest.mark.vcr
def test_fetch_injuries_returns_list() -> None:
    """IL endpoint returns a list (may be empty if no one is injured)."""
    result = fetch_injuries("DET")
    assert isinstance(result, list)
    for p in result:
        assert "name" in p
        assert "pos" in p
        assert "note" in p


@pytest.mark.vcr
def test_fetch_transactions_returns_moves() -> None:
    """Transactions endpoint returns recent roster moves with date + desc."""
    result = fetch_transactions("DET", days=14)
    assert isinstance(result, list)
    for move in result:
        assert "date" in move
        assert "desc" in move
        assert len(move["date"]) == 10  # YYYY-MM-DD


@pytest.mark.vcr
def test_fetch_live_scores_game_structure() -> None:
    """Live scores response contains correctly structured game dicts."""
    result = fetch_live_scores("DET")
    assert isinstance(result, list)
    assert len(result) >= 1
    game = result[0]
    assert "home_team" in game
    assert "away_team" in game
    assert "home_score" in game
    assert "away_score" in game
    assert "inning" in game


@pytest.mark.vcr
def test_fetch_next_game_returns_game() -> None:
    """Next game endpoint returns a dict with date, teams, and probable pitchers."""
    result = fetch_next_game("DET")
    assert isinstance(result, dict)
    assert "date" in result
    assert "home_team" in result
    assert "away_team" in result
    assert "home_probable" in result
    assert "away_probable" in result
