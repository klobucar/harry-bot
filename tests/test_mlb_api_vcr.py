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

import bigleague.http
import pytest

from mlb_api import (
    fetch_injuries,
    fetch_live_scores,
    fetch_next_game,
    fetch_roster,
    fetch_transactions,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio tests on asyncio only (avoid requiring trio)."""
    return "asyncio"


@pytest.fixture
async def fresh_client() -> None:
    """Reset bigleague's module-cached httpx.AsyncClient so a new client is
    created under the active VCR cassette (the cached one may predate it)."""
    await bigleague.http.close_client()


@pytest.mark.anyio
@pytest.mark.vcr
async def test_fetch_roster_returns_players(fresh_client: None) -> None:
    """Roster endpoint returns a non-empty list with expected fields."""
    result = await fetch_roster("DET")
    assert isinstance(result, list)
    assert len(result) > 0
    for player in result:
        assert "name" in player
        assert "pos" in player
        assert isinstance(player["name"], str)


@pytest.mark.anyio
@pytest.mark.vcr
async def test_fetch_injuries_returns_list(fresh_client: None) -> None:
    """IL endpoint returns a list (may be empty if no one is injured)."""
    result = await fetch_injuries("DET")
    assert isinstance(result, list)
    for p in result:
        assert "name" in p
        assert "pos" in p
        assert "note" in p


@pytest.mark.anyio
@pytest.mark.vcr
async def test_fetch_transactions_returns_moves(fresh_client: None) -> None:
    """Transactions endpoint returns recent roster moves with date + desc."""
    result = await fetch_transactions("DET", days=14)
    assert isinstance(result, list)
    for move in result:
        assert "date" in move
        assert "desc" in move
        assert len(move["date"]) == 10  # YYYY-MM-DD


@pytest.mark.anyio
@pytest.mark.vcr
async def test_fetch_live_scores_game_structure(fresh_client: None) -> None:
    """Live scores response contains correctly structured game dicts."""
    result = await fetch_live_scores("DET")
    assert isinstance(result, list)
    assert len(result) >= 1
    game = result[0]
    assert "home_team" in game
    assert "away_team" in game
    assert "home_score" in game
    assert "away_score" in game
    assert "inning" in game


@pytest.mark.anyio
@pytest.mark.vcr
async def test_fetch_next_game_returns_game(fresh_client: None) -> None:
    """Next game endpoint returns a dict with date, teams, and probable pitchers."""
    result = await fetch_next_game("DET")
    assert isinstance(result, dict)
    assert "date" in result
    assert "home_team" in result
    assert "away_team" in result
    assert "home_probable" in result
    assert "away_probable" in result
