"""
tests/test_playoff_hope.py — Tests for the playoff_hope helper and /hope command.

Network calls (curl_cffi) are mocked. The cache is reset between tests so
each one starts cold.
"""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import playoff_hope
from commands.info_commands import InfoCommands
from playoff_hope import (
    _parse_odds,
    _resolve_abbr,
    fetch_team_hope,
    hex_to_rgb,
    render_last_n_strip,
)


def _row(abbr: str, short: str, w: int, loss: int, **end_overrides) -> dict:
    """Build a minimal FG playoff-odds row matching the real schema."""
    end = {
        "ExpW": w + 50.0,
        "ExpL": loss + 50.0,
        "rosW": 0.5,
        "divTitle": 0.10,
        "div2Title": 0.05,
        "wcTitle": 0.05,
        "poffTitle": 0.20,
        "wcWin": 0.10,
        "dsWin": 0.05,
        "csWin": 0.02,
        "wsWin": 0.01,
    }
    end.update(end_overrides)
    return {
        "teamId": 0,
        "abbName": abbr,
        "shortName": short,
        "league": "AL",
        "division": "C",
        "W": w,
        "L": loss,
        "Wpct": w / (w + loss) if (w + loss) else 0.0,
        "GB": 0,
        "WCGB": 0,
        "dateEnd": None,
        "endData": end,
        "deltaData": None,
    }


_FG_ROWS: list[dict] = [
    _row("DET", "Tigers", 18, 18, poffTitle=0.6187, divTitle=0.4658, wcTitle=0.1529, wsWin=0.0431),
    _row("NYY", "Yankees", 24, 11, poffTitle=0.9867, divTitle=0.85, wcTitle=0.10, wsWin=0.20),
    _row("ATH", "Athletics", 18, 16, poffTitle=0.4135),
    _row("BOS", "Red Sox", 14, 21, poffTitle=0.2821),
    _row("LAA", "Angels", 13, 23, poffTitle=0.0178),
]


def _fake_html(rows: list[dict]) -> str:
    """Wrap FG rows in a minimal Next.js page so _parse_odds finds them."""
    payload = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {"queryHash": '["playoff-odds-controls"]', "state": {"data": [1, 2, 3]}},
                        {
                            "queryHash": '["playoff-odds","2026-05-05","","fg","div"]',
                            "state": {"data": rows},
                        },
                    ]
                }
            }
        }
    }
    encoded = json.dumps(payload)
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{encoded}</script></body></html>'


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level cache before and after every test."""
    playoff_hope._cache.clear()
    yield
    playoff_hope._cache.clear()


@pytest.fixture
def mock_fg(monkeypatch):
    """Patch _fetch_html and the MLB Stats API call so fetch_team_hope is hermetic."""

    def _fake(_url):
        return _fake_html(_FG_ROWS)

    monkeypatch.setattr(playoff_hope, "_fetch_html", _fake)
    monkeypatch.setattr(playoff_hope, "fetch_recent_results", lambda *_a, **_kw: [])
    return _fake


class TestHexToRgb:
    def test_parses_six_char_hex(self) -> None:
        assert hex_to_rgb("#0C2340") == (12, 35, 64)

    def test_strips_leading_hash(self) -> None:
        assert hex_to_rgb("0C2340") == (12, 35, 64)

    def test_invalid_returns_navy_fallback(self) -> None:
        assert hex_to_rgb("not a color") == (0, 40, 104)

    def test_empty_returns_navy_fallback(self) -> None:
        assert hex_to_rgb("") == (0, 40, 104)


class TestRenderLastNStrip:
    def test_empty_results_returns_empty_string(self) -> None:
        assert render_last_n_strip([]) == ""

    def test_home_win_and_loss_use_squares(self) -> None:
        out = render_last_n_strip(
            [
                {"is_home": True, "result": "W"},
                {"is_home": True, "result": "L"},
            ]
        )
        assert out == "🟩🟥"

    def test_away_win_and_loss_use_circles(self) -> None:
        out = render_last_n_strip(
            [
                {"is_home": False, "result": "W"},
                {"is_home": False, "result": "L"},
            ]
        )
        assert out == "🟢🔴"

    def test_postponed_renders_neutral(self) -> None:
        out = render_last_n_strip([{"is_home": True, "result": "P"}])
        assert out == "⚪"

    def test_mixed_strip_preserves_order(self) -> None:
        out = render_last_n_strip(
            [
                {"is_home": True, "result": "W"},
                {"is_home": False, "result": "L"},
                {"is_home": False, "result": "W"},
                {"is_home": True, "result": "L"},
            ]
        )
        assert out == "🟩🔴🟢🟥"


class TestParseOdds:
    def test_extracts_rows_from_next_data(self) -> None:
        rows = _parse_odds(_fake_html(_FG_ROWS))
        assert set(rows.keys()) == {"DET", "NYY", "ATH", "BOS", "LAA"}
        assert rows["DET"]["W"] == 18

    def test_missing_next_data_returns_empty(self) -> None:
        assert _parse_odds("<html>no next data</html>") == {}

    def test_malformed_json_returns_empty(self) -> None:
        bad = '<script id="__NEXT_DATA__" type="application/json">{not json}</script>'
        assert _parse_odds(bad) == {}


class TestResolveAbbr:
    def setup_method(self) -> None:
        self.rows = {row["abbName"]: row for row in _FG_ROWS}

    def test_exact_abbr(self) -> None:
        assert _resolve_abbr("DET", self.rows) == "DET"

    def test_lowercase_abbr(self) -> None:
        assert _resolve_abbr("det", self.rows) == "DET"

    def test_oak_aliases_to_ath(self) -> None:
        assert _resolve_abbr("OAK", self.rows) == "ATH"

    def test_unique_substring_match(self) -> None:
        assert _resolve_abbr("red sox", self.rows) == "BOS"

    def test_unknown_returns_none(self) -> None:
        assert _resolve_abbr("XYZ", self.rows) is None

    def test_empty_returns_none(self) -> None:
        assert _resolve_abbr("", self.rows) is None


class TestFetchTeamHope:
    def test_returns_full_dict_for_tigers(self, mock_fg) -> None:
        data = fetch_team_hope("DET")
        assert data["abbr"] == "DET"
        assert data["name"] == "Tigers"
        assert data["wins"] == 18
        assert data["losses"] == 18
        assert data["win_pct"] == pytest.approx(0.5)
        assert data["playoff_pct"] == pytest.approx(61.87)
        assert data["division_pct"] == pytest.approx(46.58)
        assert data["wildcard_pct"] == pytest.approx(15.29)
        assert data["ws_pct"] == pytest.approx(4.31)
        assert data["primary_color"] == "#0C2340"
        assert data["url"] == "https://mlbplayoffhope.com/#tigers"

    def test_oak_resolves_to_ath(self, mock_fg) -> None:
        data = fetch_team_hope("OAK")
        assert data["abbr"] == "ATH"
        assert data["url"] == "https://mlbplayoffhope.com/#athletics"

    def test_unknown_team_raises(self, mock_fg) -> None:
        with pytest.raises(ValueError, match="Unknown team"):
            fetch_team_hope("XYZ")

    def test_cache_avoids_duplicate_fetches(self, monkeypatch) -> None:
        calls = {"n": 0}

        def _counted(_url):
            calls["n"] += 1
            return _fake_html(_FG_ROWS)

        monkeypatch.setattr(playoff_hope, "_fetch_html", _counted)
        fetch_team_hope("DET")
        fetch_team_hope("NYY")
        fetch_team_hope("BOS")
        assert calls["n"] == 1


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


def _hope_payload(**overrides) -> dict:
    base = {
        "abbr": "DET",
        "name": "Tigers",
        "slug": "tigers",
        "primary_color": "#0C2340",
        "url": "https://mlbplayoffhope.com/#tigers",
        "wins": 18,
        "losses": 18,
        "win_pct": 0.5,
        "gb": 0,
        "proj_w": 83.4,
        "proj_l": 78.6,
        "ros_pct": 51.9,
        "playoff_pct": 61.87,
        "division_pct": 46.58,
        "wildcard_pct": 15.29,
        "ws_pct": 4.31,
        "last_results": [
            {"is_home": True, "result": "W"},
            {"is_home": False, "result": "L"},
        ],
        "last_updated": "2026-05-05 17:08 EDT",
    }
    base.update(overrides)
    return base


@pytest.mark.anyio
class TestHopeCommand:
    @patch("commands.info_commands.fetch_team_hope")
    async def test_hope_high_odds_renders_hope_label(self, mock_fetch, bot, interaction):
        mock_fetch.return_value = _hope_payload()

        cog = InfoCommands(bot)
        await cog.hope.callback(cog, interaction, "DET")  # type: ignore

        interaction.response.defer.assert_called_once_with(thinking=True)
        interaction.followup.send.assert_called_once()
        _, kwargs = interaction.followup.send.call_args
        embed: discord.Embed = kwargs["embed"]
        assert "HOPE" in embed.title
        assert "61.9%" in embed.title
        # Record/projection in description
        assert "18-18" in (embed.description or "")
        assert "83.4-78.6" in (embed.description or "")
        # Per-round breakdown in fields
        field_names = {f.name for f in embed.fields}
        assert {"Make Playoffs", "Win Division", "Win Wild Card", "Win World Series"} <= field_names
        # Last-N emoji strip rendered with home-square + away-circle scheme
        last_strip_field = next(f for f in embed.fields if "Last" in f.name)
        assert last_strip_field.value == "🟩🔴"
        # mlbplayoffhope link is the last field, as a markdown link
        last = embed.fields[-1]
        assert last.name == "Further material"
        assert "mlbplayoffhope.com" in last.value
        assert "https://mlbplayoffhope.com/#tigers" in last.value
        assert "FanGraphs" in (embed.footer.text or "")

    @patch("commands.info_commands.fetch_team_hope")
    async def test_hope_low_odds_renders_nope_label(self, mock_fetch, bot, interaction):
        mock_fetch.return_value = _hope_payload(
            abbr="LAA",
            name="Angels",
            slug="angels",
            url="https://mlbplayoffhope.com/#angels",
            wins=13,
            losses=23,
            win_pct=0.361,
            playoff_pct=1.78,
        )

        cog = InfoCommands(bot)
        await cog.hope.callback(cog, interaction, "LAA")  # type: ignore

        _, kwargs = interaction.followup.send.call_args
        embed: discord.Embed = kwargs["embed"]
        assert "NOPE" in embed.title
        assert "1.8%" in embed.title

    @patch("commands.info_commands.fetch_team_hope")
    async def test_hope_unknown_team_sends_error(self, mock_fetch, bot, interaction):
        mock_fetch.side_effect = ValueError("Unknown team 'XYZ'.")

        cog = InfoCommands(bot)
        await cog.hope.callback(cog, interaction, "XYZ")  # type: ignore

        interaction.followup.send.assert_called_once()
        args, kwargs = interaction.followup.send.call_args
        assert "Unknown team" in args[0]
        assert kwargs.get("ephemeral") is True
