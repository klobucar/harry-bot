"""
tests/test_abs.py — Unit tests for abs.py and the /abs slash command.

The Baseball Savant CSV fetch is mocked everywhere so these tests don't
hit the network.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import abs as abs_mod
from commands.info_commands import (
    InfoCommands,
    _build_league_embed,
    _build_player_embed,
    _build_team_embed,
)

# ---------------------------------------------------------------------------
# Fake CSV rows shaped like the real Savant payload.
# ---------------------------------------------------------------------------

_BATTER_ROWS = [
    {
        "entity_name": "Aaron Judge",
        "team_abbr": "NYY",
        "n_challenges": 4,
        "n_overturns": 3,
        "n_confirms": 1,
        "rate_overturns": 0.75,
        "n_strikeouts_flip": 0,
        "n_walks_flip": 1,
    },
    {
        "entity_name": "Spencer Torkelson",
        "team_abbr": "DET",
        "n_challenges": 6,
        "n_overturns": 4,
        "n_confirms": 2,
        "rate_overturns": 4 / 6,
        "n_strikeouts_flip": 1,
        "n_walks_flip": 1,
    },
    {
        "entity_name": "Singleton Sample",
        "team_abbr": "DET",
        "n_challenges": 1,
        "n_overturns": 1,
        "n_confirms": 0,
        "rate_overturns": 1.0,
        "n_strikeouts_flip": 0,
        "n_walks_flip": 0,
    },
]
_PITCHER_ROWS = [
    {
        "entity_name": "Tarik Skubal",
        "team_abbr": "DET",
        "n_challenges": 2,
        "n_overturns": 2,
        "n_confirms": 0,
        "rate_overturns": 1.0,
        "n_strikeouts_flip": 1,
        "n_walks_flip": 0,
    },
]
_CATCHER_ROWS = [
    {
        "entity_name": "Dillon Dingler",
        "team_abbr": "DET",
        "n_challenges": 21,
        "n_overturns": 19,
        "n_confirms": 2,
        "rate_overturns": 19 / 21,
        "n_strikeouts_flip": 4,
        "n_walks_flip": 0,
    },
]
_TEAM_SUMMARY_ROWS = [
    {
        "entity_name": "Detroit Tigers",
        "team_abbr": "DET",
        "n_challenges_off": 41,
        "n_overturns_off": 18,
        "rate_overturns_off": 18 / 41,
        "n_challenges_def": 27,
        "n_overturns_def": 24,
        "rate_overturns_def": 24 / 27,
        "n_strikeouts_flip_off": 6,
        "n_strikeouts_flip_def": 7,
        "n_walks_flip_off": 3,
        "n_walks_flip_def": 2,
    },
]


def _fake_fetch(year: int, role: str) -> list[dict]:
    return {
        abs_mod.ROLE_BATTER: _BATTER_ROWS,
        abs_mod.ROLE_PITCHER: _PITCHER_ROWS,
        abs_mod.ROLE_CATCHER: _CATCHER_ROWS,
        abs_mod.ROLE_TEAM_SUMMARY: _TEAM_SUMMARY_ROWS,
    }[role]


@pytest.fixture(autouse=True)
def patch_csv_fetch():
    with patch("abs._fetch_csv", side_effect=_fake_fetch):
        yield


# ---------------------------------------------------------------------------
# abs.py module
# ---------------------------------------------------------------------------


class TestNormalizeTeam:
    def test_known_alias_translates(self):
        assert abs_mod.normalize_team("OAK") == "ATH"
        assert abs_mod.normalize_team("ari") == "AZ"
        assert abs_mod.normalize_team("WAS") == "WSH"

    def test_unknown_passes_through_uppercase(self):
        assert abs_mod.normalize_team("DET") == "DET"
        assert abs_mod.normalize_team("nyy") == "NYY"


class TestFetchTeamSummary:
    def test_returns_team_row(self):
        row = abs_mod.fetch_team_summary("DET", 2026)
        assert row["team_abbr"] == "DET"
        assert row["n_challenges_off"] == 41

    def test_unknown_team_raises(self):
        with pytest.raises(ValueError, match="No ABS data"):
            abs_mod.fetch_team_summary("XYZ", 2026)


class TestFetchTeamTopChallengers:
    def test_returns_team_only_sorted(self):
        top = abs_mod.fetch_team_top_challengers("DET", 2026, limit=10)
        names = [r["entity_name"] for r in top]
        # Catcher with 21 chal beats batter with 6, then pitcher 2, then 1.
        assert names == ["Dillon Dingler", "Spencer Torkelson", "Tarik Skubal", "Singleton Sample"]
        # Each entry tagged with role
        roles = [r["role"] for r in top]
        assert roles == ["catcher", "batter", "pitcher", "batter"]

    def test_respects_limit(self):
        top = abs_mod.fetch_team_top_challengers("DET", 2026, limit=2)
        assert len(top) == 2

    def test_filters_other_teams(self):
        top = abs_mod.fetch_team_top_challengers("NYY", 2026)
        assert all(r["team_abbr"] == "NYY" for r in top)


class TestFetchPlayer:
    def test_finds_in_batter_feed(self):
        out = abs_mod.fetch_player("Aaron", "Judge", 2026)
        assert out["name"] == "Aaron Judge"
        assert out["team_abbr"] == "NYY"
        assert out["totals"]["n_challenges"] == 4
        assert len(out["roles"]) == 1
        assert out["roles"][0]["role"] == "batter"

    def test_unknown_player_raises(self):
        with pytest.raises(ValueError, match="No ABS challenge data"):
            abs_mod.fetch_player("Mickey", "Mouse", 2026)

    def test_case_insensitive(self):
        out = abs_mod.fetch_player("aaron", "JUDGE", 2026)
        assert out["name"] == "Aaron Judge"


class TestFetchLeagueLeaders:
    def test_filters_by_min_challenges(self):
        out = abs_mod.fetch_league_leaders(2026, limit=10, min_challenges=3)
        names = [r["entity_name"] for r in out]
        # "Singleton Sample" has 1 challenge — below the floor — should be cut.
        # "Tarik Skubal" has 2 challenges — also cut at min=3.
        assert "Singleton Sample" not in names
        assert "Tarik Skubal" not in names

    def test_sorts_by_rate_then_count(self):
        out = abs_mod.fetch_league_leaders(2026, limit=10, min_challenges=1)
        # Top 3 all 100%: Singleton (1 chal), Skubal (2), Dingler is 90%.
        # Sort breaks ties on n_challenges desc → Skubal before Singleton.
        assert out[0]["entity_name"] == "Tarik Skubal"
        assert out[1]["entity_name"] == "Singleton Sample"


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------


class TestEmbedBuilders:
    def test_team_embed_has_summary_and_top(self):
        embed = _build_team_embed("DET", 2026)
        assert "Detroit Tigers" in (embed.title or "")
        assert "ABS" in (embed.title or "")
        # Total challenges = off + def
        assert "68" in (embed.description or "")
        # Has Offense, Defense, Top challengers fields
        names = [f.name or "" for f in embed.fields]
        assert any("Offense" in n for n in names)
        assert any("Defense" in n for n in names)
        assert any("Top challengers" in n for n in names)
        # Top challengers includes Dingler
        top_field = next(f for f in embed.fields if "Top" in (f.name or ""))
        assert "Dillon Dingler" in (top_field.value or "")

    def test_player_embed_has_stats(self):
        embed = _build_player_embed("Aaron", "Judge", 2026)
        assert "Aaron Judge" in (embed.title or "")
        # 4 challenges, 75% success
        assert "4 challenges" in (embed.description or "")
        assert "75.0%" in (embed.description or "")

    def test_league_embed_lists_leaders(self):
        embed = _build_league_embed(2026)
        # Single description blob; just verify a couple of expected names.
        text = embed.description or ""
        assert "Tarik Skubal" in text or "Dillon Dingler" in text


# ---------------------------------------------------------------------------
# /abs slash command
# ---------------------------------------------------------------------------


@pytest.fixture
def bot() -> MagicMock:
    return MagicMock()


@pytest.fixture
def interaction() -> discord.Interaction:
    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.response = MagicMock()
    mock_interaction.response.defer = AsyncMock()
    mock_interaction.response.send_message = AsyncMock()
    mock_interaction.followup = MagicMock()
    mock_interaction.followup.send = AsyncMock()
    return cast("discord.Interaction", mock_interaction)


@pytest.mark.anyio
class TestAbsCommand:
    async def test_team_view(self, bot, interaction):
        cog = InfoCommands(bot)
        await cog.abs_cmd.callback(cog, interaction, team="DET", year=2026)  # type: ignore
        interaction.response.defer.assert_called_once_with(thinking=True)
        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        assert "Detroit Tigers" in kwargs["embed"].title

    async def test_league_view_when_no_team(self, bot, interaction):
        cog = InfoCommands(bot)
        await cog.abs_cmd.callback(cog, interaction, year=2026)  # type: ignore
        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        assert "Leaders" in kwargs["embed"].title

    async def test_pre_2026_year_rejected(self, bot, interaction):
        cog = InfoCommands(bot)
        await cog.abs_cmd.callback(cog, interaction, year=2025)  # type: ignore
        # Should error before defer.
        interaction.response.send_message.assert_called_once()
        interaction.response.defer.assert_not_called()

    async def test_unknown_team_handled(self, bot, interaction):
        cog = InfoCommands(bot)
        await cog.abs_cmd.callback(cog, interaction, team="XYZ", year=2026)  # type: ignore
        interaction.followup.send.assert_called_once()
        args, _ = interaction.followup.send.call_args
        assert "No ABS data" in args[0]


@pytest.mark.anyio
class TestPlayerAbsCommand:
    async def test_player_view(self, bot, interaction):
        cog = InfoCommands(bot)
        cb = cast("Any", cog.playerabs.callback)
        await cb(cog, interaction, first_name="Aaron", last_name="Judge", year=2026)
        interaction.response.defer.assert_called_once_with(thinking=True)
        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        assert "Aaron Judge" in kwargs["embed"].title

    async def test_pre_2026_year_rejected(self, bot, interaction):
        cog = InfoCommands(bot)
        cb = cast("Any", cog.playerabs.callback)
        await cb(cog, interaction, first_name="Aaron", last_name="Judge", year=2025)
        interaction.response.send_message.assert_called_once()
        interaction.response.defer.assert_not_called()

    async def test_unknown_player_handled(self, bot, interaction):
        cog = InfoCommands(bot)
        cb = cast("Any", cog.playerabs.callback)
        await cb(cog, interaction, first_name="Mickey", last_name="Mouse", year=2026)
        interaction.followup.send.assert_called_once()
        args, _ = interaction.followup.send.call_args
        assert "No ABS challenge data" in args[0]
