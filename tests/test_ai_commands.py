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
    # Generic exceptions surface a class-name label, not the raw message
    assert "General Error" not in args[0]
    assert "Exception" in args[0]


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_client_error_swallowed(mock_client_class, bot, interaction):
    from google.genai.errors import ClientError

    # Setup mock client to raise a Gemini ClientError
    mock_client = mock_client_class.return_value
    # ClientError requires code (int) and response_json arguments
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=ClientError(429, response_json={})
    )

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
async def test_junkstats_falls_back_on_rate_limit(mock_client_class, bot, interaction):
    from google.genai.errors import ClientError

    from commands.ai_commands import MODEL_LADDER

    mock_client = mock_client_class.return_value
    mock_response = MagicMock()
    mock_response.text = (
        "The **1962 Mets** lost exactly 120 games in a season with no dome stadiums."
    )
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[ClientError(429, response_json={}), mock_response]
    )

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    assert mock_client.aio.models.generate_content.call_count == 2
    first_call, second_call = mock_client.aio.models.generate_content.call_args_list
    assert first_call.kwargs["model"] == MODEL_LADDER[0]
    assert second_call.kwargs["model"] == MODEL_LADDER[1]

    interaction.followup.send.assert_called_once()
    args, _ = interaction.followup.send.call_args
    assert "1962 Mets" in args[0]


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_falls_back_on_server_unavailable(mock_client_class, bot, interaction):
    from google.genai.errors import ServerError

    from commands.ai_commands import MODEL_LADDER

    mock_client = mock_client_class.return_value
    mock_response = MagicMock()
    mock_response.text = (
        "The **1962 Mets** lost exactly 120 games in a season with no dome stadiums."
    )
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[ServerError(503, response_json={}), mock_response]
    )

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    assert mock_client.aio.models.generate_content.call_count == 2
    first_call, second_call = mock_client.aio.models.generate_content.call_args_list
    assert first_call.kwargs["model"] == MODEL_LADDER[0]
    assert second_call.kwargs["model"] == MODEL_LADDER[1]

    interaction.followup.send.assert_called_once()
    args, _ = interaction.followup.send.call_args
    assert "1962 Mets" in args[0]


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_non_retryable_client_error_does_not_fall_back(
    mock_client_class, bot, interaction
):
    from google.genai.errors import ClientError

    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=ClientError(400, response_json={})
    )

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    assert mock_client.aio.models.generate_content.call_count == 1
    interaction.followup.send.assert_called_once()


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_retries_once_on_truncation(mock_client_class, bot, interaction):
    from google.genai import types

    truncated_response = MagicMock()
    truncated_response.text = "Cap Anson committed exactly 43 errors while"
    truncated_response.candidates = [MagicMock(finish_reason=types.FinishReason.MAX_TOKENS)]

    complete_response = MagicMock()
    complete_response.text = (
        "**Cap Anson** committed exactly 43 errors while playing third base in 1879."
    )
    complete_response.candidates = [MagicMock(finish_reason=types.FinishReason.STOP)]

    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[truncated_response, complete_response]
    )

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    assert mock_client.aio.models.generate_content.call_count == 2
    interaction.followup.send.assert_called_once()
    args, _ = interaction.followup.send.call_args
    assert "playing third base" in args[0]


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_sends_text_if_still_truncated_after_retry(
    mock_client_class, bot, interaction
):
    from google.genai import types

    truncated_response = MagicMock()
    truncated_response.text = "Cap Anson committed exactly 43 errors while"
    truncated_response.candidates = [MagicMock(finish_reason=types.FinishReason.MAX_TOKENS)]

    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(return_value=truncated_response)

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    # Only one retry -- no infinite loop chasing a clean finish_reason.
    assert mock_client.aio.models.generate_content.call_count == 2
    interaction.followup.send.assert_called_once()
    args, _ = interaction.followup.send.call_args
    assert "Cap Anson" in args[0]


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


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_steps_down_on_timeout(mock_client_class, bot, interaction):
    from commands.ai_commands import MODEL_LADDER

    mock_response = MagicMock()
    mock_response.text = "**Rickey Henderson** stole exactly 3 bases on Tuesdays in May 1982."
    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[asyncio.TimeoutError, mock_response]
    )

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    first_call, second_call = mock_client.aio.models.generate_content.call_args_list
    assert first_call.kwargs["model"] == MODEL_LADDER[0]
    assert second_call.kwargs["model"] == MODEL_LADDER[1]
    args, _ = interaction.followup.send.call_args
    assert "Rickey Henderson" in args[0]


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.MODEL_LADDER", ("rung-a", "rung-b", "rung-c"))
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_climbs_full_ladder(mock_client_class, bot, interaction):
    from google.genai.errors import ClientError, ServerError

    mock_response = MagicMock()
    mock_response.text = "The **1884 Quicksteps** turned exactly 7 double plays on Thursdays."
    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[
            ClientError(429, response_json={}),
            ServerError(503, response_json={}),
            mock_response,
        ]
    )

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    models = [c.kwargs["model"] for c in mock_client.aio.models.generate_content.call_args_list]
    assert models == ["rung-a", "rung-b", "rung-c"]
    args, _ = interaction.followup.send.call_args
    assert "1884 Quicksteps" in args[0]


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_every_rung_rate_limited(mock_client_class, bot, interaction):
    from google.genai.errors import ClientError

    from commands.ai_commands import MODEL_LADDER

    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=ClientError(429, response_json={})
    )

    cog = AICommands(bot)
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    assert mock_client.aio.models.generate_content.call_count == len(MODEL_LADDER)
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert kwargs["ephemeral"] is True
