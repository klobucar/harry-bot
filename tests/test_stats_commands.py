"""
tests/test_stats_commands.py — Unit tests for FanGraphs stats slash commands.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from commands.stats_commands import StatsCommands


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
class TestStatsCommands:
    @patch("commands.stats_commands.fetch_player_stats")
    async def test_stats_success_pitcher(self, mock_fetch, bot, interaction):
        # Setup mock data

        mock_fetch.return_value = {
            "type": "pitcher",
            "team": "DET",
            "stats": {"ERA": 2.39, "IP": 192.0},
        }

        cog = StatsCommands(bot)
        # Using the callback directly to avoid complex slash command registration
        await cog.stats.callback(cog, interaction, "Tarik", "Skubal", 2024)  # type: ignore

        interaction.response.defer.assert_called_once_with(thinking=True)
        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        embed = kwargs["embed"]
        assert "Tarik Skubal" in embed.title
        # Stats are in fields
        assert any(f.name == "ERA" and f.value == "2.39" for f in embed.fields)

    @patch("commands.stats_commands.fetch_player_stats")
    async def test_stats_player_not_found(self, mock_fetch, bot, interaction):
        mock_fetch.side_effect = ValueError("Player not found")

        cog = StatsCommands(bot)
        await cog.stats.callback(cog, interaction, "Fake", "Player", 2024)  # type: ignore

        interaction.followup.send.assert_called_once()
        args, _ = interaction.followup.send.call_args
        assert "not found" in args[0].lower()
