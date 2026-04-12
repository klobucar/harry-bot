"""
tests/test_mlb_commands.py — Unit tests for MLB lifecycle slash commands.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from commands.mlb_commands import MLBCommands


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
class TestMLBCommands:
    @patch("commands.mlb_commands.fetch_roster")
    async def test_roster_success(self, mock_fetch, bot, interaction):
        # Setup mock data
        mock_fetch.return_value = [{"name": "Tarik Skubal", "pos": "SP", "status": "Active"}]

        cog = MLBCommands(bot)
        await cog.roster.callback(cog, interaction, "DET")  # type: ignore

        # Verify interaction flow
        interaction.response.defer.assert_called_once_with(thinking=True)
        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        embed = kwargs["embed"]
        assert isinstance(embed, discord.Embed)
        assert "Active Roster" in embed.title
        # Player name is in a field value code block
        assert "Tarik Skubal" in embed.fields[0].value

    @patch("commands.mlb_commands.fetch_roster")
    async def test_roster_error_handled(self, mock_fetch, bot, interaction):
        # Setup mock to raise error
        mock_fetch.side_effect = ValueError("Unknown team")

        cog = MLBCommands(bot)
        await cog.roster.callback(cog, interaction, "XYZ")  # type: ignore

        # Verify error message sent
        interaction.followup.send.assert_called_once()
        args, _ = interaction.followup.send.call_args
        assert "Unknown team" in args[0]

    @patch("commands.mlb_commands.fetch_live_scores")
    async def test_livescore_success(self, mock_fetch, bot, interaction):
        mock_fetch.return_value = [
            {
                "home_team": "Detroit Tigers",
                "away_team": "Cleveland Guardians",
                "home_score": 3,
                "away_score": 2,
                "status": "In Progress",
                "inning": "Bottom 7th",
                "outs": 2,
            }
        ]

        cog = MLBCommands(bot)
        await cog.livescore.callback(cog, interaction, "DET")  # type: ignore

        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        embed = kwargs["embed"]
        assert "Live Score" in embed.title
        # Team name is in the field name
        assert "Detroit Tigers" in embed.fields[0].name
        assert "3" in embed.fields[0].name
        assert "2" in embed.fields[0].name

    @patch("commands.mlb_commands.fetch_next_game")
    async def test_nextgame_success(self, mock_fetch, bot, interaction):
        mock_fetch.return_value = {
            "date": "2025-04-05",
            "time": "18:10 UTC",
            "home_team": "Detroit Tigers",
            "away_team": "Chicago White Sox",
            "home_probable": "Tarik Skubal",
            "away_probable": "Garrett Crochet",
        }

        cog = MLBCommands(bot)
        await cog.nextgame.callback(cog, interaction, "DET")  # type: ignore

        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        embed = kwargs["embed"]
        assert "Next Game" in embed.title
        # Probable pitcher is in a field
        assert "Tarik Skubal" in embed.fields[1].value
