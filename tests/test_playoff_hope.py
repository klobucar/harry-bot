"""
tests/test_playoff_hope.py — Tests for the playoff_hope helper and /hope command.

The FanGraphs fetch/parse now lives in ``bigleague`` (async, polars). This
module keeps only Discord-presentation logic, so the data layer is mocked at
the ``playoff_hope.playoff_odds`` / ``playoff_hope.recent_results`` boundary.
The module-level cache is reset between tests so each one starts cold.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import polars as pl
import pytest

import playoff_hope
from commands.info_commands import InfoCommands
from playoff_hope import (
    _pct,
    _resolve_abbr,
    fetch_team_hope,
    hex_to_rgb,
    render_last_n_strip,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio tests on asyncio only (trio is not installed)."""
    return "asyncio"


def _odds_row(abbr: str, short: str, w: int, loss: int, **overrides) -> dict:
    """Build a minimal playoff-odds frame row matching bigleague's schema.

    Probabilities are RAW FRACTIONS in [0, 1]; fetch_team_hope scales them to
    percent via _pct.
    """
    row = {
        "abbName": abbr,
        "shortName": short,
        "W": w,
        "L": loss,
        "Wpct": (w / (w + loss)) if (w + loss) else 0.0,
        "GB": 0.0,
        "exp_w": w + 50.0,
        "exp_l": loss + 50.0,
        "ros_pct": 0.5,
        "playoff_pct": 0.20,
        "division_pct": 0.10,
        "wildcard_pct": 0.05,
        "ws_pct": 0.01,
    }
    row.update(overrides)
    return row


_FG_ROWS: list[dict] = [
    _odds_row(
        "DET",
        "Tigers",
        18,
        18,
        playoff_pct=0.6187,
        division_pct=0.4658,
        wildcard_pct=0.1529,
        ws_pct=0.0431,
    ),
    _odds_row("NYY", "Yankees", 24, 11, playoff_pct=0.9867, division_pct=0.85, ws_pct=0.20),
    _odds_row("ATH", "Athletics", 18, 16, playoff_pct=0.4135),
    _odds_row("BOS", "Red Sox", 14, 21, playoff_pct=0.2821),
    _odds_row("LAA", "Angels", 13, 23, playoff_pct=0.0178),
]


def _odds_frame(rows: list[dict] | None = None) -> pl.DataFrame:
    return pl.DataFrame(rows if rows is not None else _FG_ROWS)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level cache before and after every test."""
    playoff_hope._cache.clear()
    yield
    playoff_hope._cache.clear()


# ---------------------------------------------------------------------------
# hex_to_rgb
# ---------------------------------------------------------------------------


class TestHexToRgb:
    def test_parses_six_char_hex(self) -> None:
        assert hex_to_rgb("#0C2340") == (12, 35, 64)

    def test_strips_leading_hash(self) -> None:
        assert hex_to_rgb("0C2340") == (12, 35, 64)

    def test_invalid_returns_navy_fallback(self) -> None:
        assert hex_to_rgb("not a color") == (0, 40, 104)

    def test_empty_returns_navy_fallback(self) -> None:
        assert hex_to_rgb("") == (0, 40, 104)


# ---------------------------------------------------------------------------
# _pct
# ---------------------------------------------------------------------------


class TestPct:
    def test_fraction_scales_to_percent(self) -> None:
        assert _pct(0.6187) == pytest.approx(61.87)

    def test_zero_stays_zero(self) -> None:
        assert _pct(0.0) == 0.0

    def test_none_returns_zero(self) -> None:
        assert _pct(None) == 0.0

    def test_bad_value_returns_zero(self) -> None:
        assert _pct("not a number") == 0.0


# ---------------------------------------------------------------------------
# render_last_n_strip
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# _resolve_abbr
# ---------------------------------------------------------------------------


class TestResolveAbbr:
    def setup_method(self) -> None:
        self.rows = {row["abbName"]: {"shortName": row["shortName"]} for row in _FG_ROWS}

    def test_exact_abbr(self) -> None:
        assert _resolve_abbr("DET", self.rows) == "DET"

    def test_lowercase_abbr(self) -> None:
        assert _resolve_abbr("det", self.rows) == "DET"

    def test_oak_aliases_to_ath(self) -> None:
        assert _resolve_abbr("OAK", self.rows) == "ATH"

    def test_unique_substring_match(self) -> None:
        assert _resolve_abbr("red sox", self.rows) == "BOS"

    def test_ambiguous_substring_returns_none(self) -> None:
        # "a" appears in several shortNames (Athletics, Angels, ...).
        assert _resolve_abbr("a", self.rows) is None

    def test_unknown_returns_none(self) -> None:
        assert _resolve_abbr("XYZ", self.rows) is None

    def test_empty_returns_none(self) -> None:
        assert _resolve_abbr("", self.rows) is None


# ---------------------------------------------------------------------------
# fetch_team_hope (mocked at the bigleague boundary)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestFetchTeamHope:
    async def test_returns_full_dict_for_tigers(self) -> None:
        playoff_hope._cache.clear()
        with (
            patch("playoff_hope.playoff_odds", new=AsyncMock(return_value=_odds_frame())),
            patch("playoff_hope.recent_results", new=AsyncMock(return_value=[])),
        ):
            data = await fetch_team_hope("DET")

        assert data["abbr"] == "DET"
        assert data["name"] == "Tigers"
        assert data["slug"] == "tigers"
        assert data["wins"] == 18
        assert data["losses"] == 18
        assert data["win_pct"] == pytest.approx(0.5)
        assert data["playoff_pct"] == pytest.approx(61.87)
        assert data["division_pct"] == pytest.approx(46.58)
        assert data["wildcard_pct"] == pytest.approx(15.29)
        assert data["ws_pct"] == pytest.approx(4.31)
        assert data["primary_color"] == "#0C2340"
        assert data["url"] == "https://mlbplayoffhope.com/#tigers"
        assert data["last_results"] == []

    async def test_oak_resolves_to_ath(self) -> None:
        playoff_hope._cache.clear()
        with (
            patch("playoff_hope.playoff_odds", new=AsyncMock(return_value=_odds_frame())),
            patch("playoff_hope.recent_results", new=AsyncMock(return_value=[])),
        ):
            data = await fetch_team_hope("OAK")

        assert data["abbr"] == "ATH"
        assert data["slug"] == "athletics"
        assert data["url"] == "https://mlbplayoffhope.com/#athletics"

    async def test_recent_results_failure_yields_empty_last_results(self) -> None:
        playoff_hope._cache.clear()
        with (
            patch("playoff_hope.playoff_odds", new=AsyncMock(return_value=_odds_frame())),
            patch("playoff_hope.recent_results", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            data = await fetch_team_hope("DET")

        assert data["last_results"] == []

    async def test_recent_results_passed_through(self) -> None:
        playoff_hope._cache.clear()
        games = [{"is_home": True, "result": "W"}, {"is_home": False, "result": "L"}]
        with (
            patch("playoff_hope.playoff_odds", new=AsyncMock(return_value=_odds_frame())),
            patch("playoff_hope.recent_results", new=AsyncMock(return_value=games)),
        ):
            data = await fetch_team_hope("DET")

        assert data["last_results"] == games

    async def test_unknown_team_raises(self) -> None:
        playoff_hope._cache.clear()
        with (
            patch("playoff_hope.playoff_odds", new=AsyncMock(return_value=_odds_frame())),
            patch("playoff_hope.recent_results", new=AsyncMock(return_value=[])),
            pytest.raises(ValueError, match="Unknown team"),
        ):
            await fetch_team_hope("XYZ")

    async def test_cache_avoids_duplicate_fetches(self) -> None:
        playoff_hope._cache.clear()
        odds = AsyncMock(return_value=_odds_frame())
        with (
            patch("playoff_hope.playoff_odds", new=odds),
            patch("playoff_hope.recent_results", new=AsyncMock(return_value=[])),
        ):
            await fetch_team_hope("DET")
            await fetch_team_hope("NYY")
            await fetch_team_hope("BOS")

        assert odds.call_count == 1


# ---------------------------------------------------------------------------
# /hope command
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
        assert "HOPE" in (embed.title or "")
        assert "61.9%" in (embed.title or "")
        # Record/projection in description
        assert "18-18" in (embed.description or "")
        assert "83.4-78.6" in (embed.description or "")
        # Per-round breakdown in fields
        field_names = {f.name for f in embed.fields}
        assert {"Make Playoffs", "Win Division", "Win Wild Card", "Win World Series"} <= field_names
        # Last-N emoji strip rendered with home-square + away-circle scheme
        last_strip_field = next(f for f in embed.fields if "Last" in (f.name or ""))
        assert last_strip_field.value == "🟩🔴"
        # mlbplayoffhope link is the last field, as a markdown link
        last = embed.fields[-1]
        assert last.name == "Further material"
        assert "mlbplayoffhope.com" in (last.value or "")
        assert "https://mlbplayoffhope.com/#tigers" in (last.value or "")
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
        assert "NOPE" in (embed.title or "")
        assert "1.8%" in (embed.title or "")

    @patch("commands.info_commands.fetch_team_hope")
    async def test_hope_unknown_team_sends_error(self, mock_fetch, bot, interaction):
        mock_fetch.side_effect = ValueError("Unknown team 'XYZ'.")

        cog = InfoCommands(bot)
        await cog.hope.callback(cog, interaction, "XYZ")  # type: ignore

        interaction.followup.send.assert_called_once()
        args, kwargs = interaction.followup.send.call_args
        assert "Unknown team" in args[0]
        assert kwargs.get("ephemeral") is True
