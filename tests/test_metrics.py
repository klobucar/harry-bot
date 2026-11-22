"""Tests for metrics.py and the places that record metrics."""

from __future__ import annotations

import asyncio
import os
import time
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from prometheus_client import REGISTRY

import metrics
from bot import _record_duration


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@patch.dict(os.environ, {}, clear=True)
@patch("metrics.start_http_server")
def test_metrics_server_off_without_port(mock_start):
    assert metrics.start_metrics_server() is None
    mock_start.assert_not_called()


@patch.dict(os.environ, {"HARRY_METRICS_PORT": "nine"})
@patch("metrics.start_http_server")
def test_metrics_server_ignores_invalid_port(mock_start):
    assert metrics.start_metrics_server() is None
    mock_start.assert_not_called()


@patch.dict(os.environ, {"HARRY_METRICS_PORT": "9091"})
@patch("metrics.start_http_server")
def test_metrics_server_starts_on_port(mock_start):
    assert metrics.start_metrics_server() == 9091
    mock_start.assert_called_once_with(9091, addr="0.0.0.0")  # noqa: S104


@patch.dict(os.environ, {"HARRY_METRICS_PORT": "9091"})
@patch("metrics.start_http_server", side_effect=OSError("address in use"))
def test_metrics_server_failure_does_not_raise(mock_start):
    assert metrics.start_metrics_server() is None


def _interaction(command_name: str | None, t0: float | None) -> discord.Interaction:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.extras = {} if t0 is None else {"t0": t0}
    interaction.command = MagicMock(qualified_name=command_name) if command_name else None
    return cast("discord.Interaction", interaction)


def test_record_duration_observes_histogram():
    labels = {"command": "metrics_test_cmd", "outcome": "ok"}
    before = _sample("harry_command_duration_seconds_count", **labels)

    _record_duration(_interaction("metrics_test_cmd", time.perf_counter() - 1.5), "ok")

    assert _sample("harry_command_duration_seconds_count", **labels) == before + 1
    assert _sample("harry_command_duration_seconds_sum", **labels) >= 1.5


def test_record_duration_skips_without_start_time():
    labels = {"command": "metrics_untimed_cmd", "outcome": "error"}
    _record_duration(_interaction("metrics_untimed_cmd", None), "error")
    assert _sample("harry_command_duration_seconds_count", **labels) == 0.0


def test_record_duration_labels_unknown_command():
    labels = {"command": "unknown", "outcome": "cooldown"}
    before = _sample("harry_command_duration_seconds_count", **labels)
    _record_duration(_interaction(None, time.perf_counter()), "cooldown")
    assert _sample("harry_command_duration_seconds_count", **labels) == before + 1


@pytest.mark.anyio
@patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"})
@patch("commands.ai_commands.MODEL_LADDER", ("metrics-rung-a", "metrics-rung-b", "metrics-rung-c"))
@patch("commands.ai_commands.genai.Client")
async def test_junkstats_counts_each_rung(mock_client_class):
    from google.genai.errors import ServerError

    from commands.ai_commands import AICommands

    mock_response = MagicMock()
    mock_response.text = "**Rickey Henderson** stole exactly 3 bases on Tuesdays in May 1982."
    mock_client = mock_client_class.return_value
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[asyncio.TimeoutError, ServerError(503, response_json={}), mock_response]
    )
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock(defer=AsyncMock(), send_message=AsyncMock())
    interaction.followup = MagicMock(send=AsyncMock())

    name = "harry_junkstats_attempts_total"
    before = {
        ("metrics-rung-a", "timeout"): _sample(name, model="metrics-rung-a", result="timeout"),
        ("metrics-rung-b", "503"): _sample(name, model="metrics-rung-b", result="503"),
        ("metrics-rung-c", "ok"): _sample(name, model="metrics-rung-c", result="ok"),
    }

    cog = AICommands(MagicMock())
    await cog.junkstats.callback(cog, interaction)  # type: ignore

    for (model, result), value in before.items():
        assert _sample(name, model=model, result=result) == value + 1
