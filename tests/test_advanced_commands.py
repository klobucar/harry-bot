"""
tests/test_advanced_commands.py — Unit tests for advanced stat slash commands.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from commands.advanced_commands import AdvancedCommands


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
class TestAdvancedCommands:
    @patch("commands.advanced_commands.fetch_leaderboard")
    async def test_leaderboard_success(self, mock_fetch, bot, interaction):
        mock_fetch.return_value = [
            {"rank": 1, "name": "Tarik Skubal", "team": "DET", "value": 2.39},
            {"rank": 2, "name": "Chris Sale", "team": "ATL", "value": 2.50},
        ]

        cog = AdvancedCommands(bot)
        await cog.leaderboard.callback(cog, interaction, "ERA", 2024, "pitcher")  # type: ignore

        interaction.response.defer.assert_called_once()
        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        embed = kwargs["embed"]
        assert "ERA Leaders" in embed.title
        assert "Tarik Skubal" in embed.description

    @patch("commands.advanced_commands.resolve_player_id")
    @patch("commands.advanced_commands.fetch_exit_velo")
    async def test_exitvelo_success(self, mock_fetch, mock_resolve, bot, interaction):
        mock_resolve.return_value = 123456
        mock_fetch.return_value = {"Avg Exit Velo": 92.3, "Max Exit Velo": 112.4}

        cog = AdvancedCommands(bot)
        await cog.exitvelo.callback(cog, interaction, "Riley", "Greene", 2024)  # type: ignore

        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        embed = kwargs["embed"]
        assert "Exit Velocity" in embed.title
        assert any(f.name == "Avg Exit Velo" and f.value == "92.3" for f in embed.fields)

    @patch("commands.advanced_commands.resolve_player_id")
    @patch("commands.advanced_commands.fetch_percentile_ranks")
    async def test_percentile_success(self, mock_fetch, mock_resolve, bot, interaction):
        mock_resolve.return_value = 123456
        mock_fetch.return_value = {"xERA": "99th percentile", "K%": "95th percentile"}

        cog = AdvancedCommands(bot)
        await cog.percentile.callback(cog, interaction, "Tarik", "Skubal", 2024, "pitcher")  # type: ignore

        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        embed = kwargs["embed"]
        assert "Percentile Ranks" in embed.title
        assert any(f.name == "xERA" and f.value == "99th percentile" for f in embed.fields)
