import asyncio
import os
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from commands.ai_commands import AICommands


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
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_success(mock_client_class, bot, interaction):
    # Setup mock client and response
    mock_client = mock_client_class.return_value
    mock_response = MagicMock()
    mock_response.text = "Prince Fielder and his father Cecil Fielder both finished their MLB careers with exactly 319 home runs."
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    # Verify interaction
    interaction.response.defer.assert_called_once_with(thinking=True)
    interaction.followup.send.assert_called_once()
    args, _ = interaction.followup.send.call_args
    assert "Prince Fielder" in args[0]

@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": ""})
async def test_junkstats_no_api_key(bot, interaction):
    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    assert "Gemini API key is missing" in args[0]
    assert kwargs["ephemeral"] is True

@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_api_error(mock_client_class, bot, interaction):
    # Setup mock client to raise a generic exception
    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("General Error"))

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    interaction.followup.send.assert_called_once()
    args, _ = interaction.followup.send.call_args
    # Generic exceptions should still show technical details
    assert "General Error" in args[0]

@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_client_error_swallowed(mock_client_class, bot, interaction):
    from google.genai.errors import ClientError
    # Setup mock client to raise a Gemini ClientError
    mock_client = mock_client_class.return_value
    # ClientError requires code (int) and response_json arguments
    mock_client.aio.models.generate_content = AsyncMock(side_effect=ClientError(429, response_json={}))

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    interaction.followup.send.assert_called_once()
    args, _ = interaction.followup.send.call_args
    # ClientErrors (like 429) should NOT show technical details
    assert "Quota Exceeded" not in args[0]
    # It should still be a Harry quote (from persona.py)
    from persona import HARRY_ERRORS
    assert any(q in args[0] for q in HARRY_ERRORS)

@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_timeout(mock_client_class, bot, interaction):
    # Setup mock client to raise TimeoutError
    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(side_effect=asyncio.TimeoutError)

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    interaction.followup.send.assert_called_once()
    args, _ = interaction.followup.send.call_args
    assert "unresponsive" in args[0]
