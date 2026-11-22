"""
tests/test_visual_statcast.py — Unit tests for the Statcast plot facade.

The data/plot layer now sits on `bigleague` (async, polars). Each
``fetch_*`` helper in ``statcast_plots`` (re-exported by ``statcast``):

  * fetches a season frame via ``bigleague.statcast_season`` (async → polars),
  * renders it with a SYNC ``bigleague.plots.*`` function (returns raw PNG
    ``bytes``), wrapped in a ``BytesIO`` via ``asyncio.to_thread``.

These tests mock those two boundaries: ``bigleague.statcast_season`` (an
``AsyncMock`` returning a polars frame, or an empty frame to drive the
"no data" ``ValueError`` path) and the relevant ``bigleague.plots.*``
function (a sync ``MagicMock`` returning sentinel bytes, or raising to drive
error paths). Rendering correctness is bigleague's concern, tested there.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import polars as pl
import pytest

import statcast_plots  # noqa: F401 — registers module so patch("statcast_plots.X") works
from statcast import (
    fetch_batter_zone,
    fetch_hitter_hotzones,
    fetch_matchup_zone,
    fetch_pitcher_zone,
    fetch_spray_chart,
    fetch_stadium_info,
)

PNG = b"PNGBYTES"


@pytest.fixture
def mock_statcast_df() -> pl.DataFrame:
    """Return a minimal Statcast-shaped polars frame."""
    return pl.DataFrame(
        [
            {
                "zone": 1.0,
                "events": "home_run",
                "pitch_type": "FF",
                "type": "X",
                "plate_x": 0.0,
                "plate_z": 2.5,
                "hc_x": 125.0,
                "hc_y": 180.0,
                "home_team": "DET",
            },
            {
                "zone": 1.0,
                "events": "field_out",
                "pitch_type": "SL",
                "type": "X",
                "plate_x": 0.1,
                "plate_z": 2.6,
                "hc_x": 130.0,
                "hc_y": 190.0,
                "home_team": "DET",
            },
            {
                "zone": 5.0,
                "events": "single",
                "pitch_type": "FF",
                "type": "X",
                "plate_x": 0.0,
                "plate_z": 2.0,
                "hc_x": 120.0,
                "hc_y": 170.0,
                "home_team": "DET",
            },
        ]
    )


def _assert_png_buffer(result: object) -> None:
    assert isinstance(result, io.BytesIO)
    assert result.read() == PNG


# ---------------------------------------------------------------------------
# fetch_hitter_hotzones
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_hitter_hotzones_success(mock_statcast_df: pl.DataFrame) -> None:
    with (
        patch("bigleague.statcast_season", return_value=mock_statcast_df),
        patch("bigleague.plots.hot_zones", return_value=PNG) as mock_plot,
    ):
        result = await fetch_hitter_hotzones(123456, 2024, "Test Player")

    _assert_png_buffer(result)
    mock_plot.assert_called_once()


@pytest.mark.anyio
async def test_fetch_hitter_hotzones_empty_raises() -> None:
    with (
        patch("bigleague.statcast_season", return_value=pl.DataFrame()),
        pytest.raises(ValueError, match="No Statcast batter data"),
    ):
        await fetch_hitter_hotzones(123456, 2024, "Test Player")


# ---------------------------------------------------------------------------
# Standard strike zone plotters
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_pitcher_zone(mock_statcast_df: pl.DataFrame) -> None:
    with (
        patch("bigleague.statcast_season", return_value=mock_statcast_df),
        patch("bigleague.plots.strike_zone", return_value=PNG) as mock_plot,
    ):
        result = await fetch_pitcher_zone(123456, 2024, "Test Pitcher")

    _assert_png_buffer(result)
    mock_plot.assert_called_once()


@pytest.mark.anyio
async def test_fetch_pitcher_zone_empty_raises() -> None:
    with (
        patch("bigleague.statcast_season", return_value=pl.DataFrame()),
        pytest.raises(ValueError, match="No Statcast pitcher data"),
    ):
        await fetch_pitcher_zone(123456, 2024, "Test Pitcher")


@pytest.mark.anyio
async def test_fetch_batter_zone(mock_statcast_df: pl.DataFrame) -> None:
    with (
        patch("bigleague.statcast_season", return_value=mock_statcast_df),
        patch("bigleague.plots.batter_zone", return_value=PNG) as mock_plot,
    ):
        result = await fetch_batter_zone(123456, 2024, "Test Batter")

    _assert_png_buffer(result)
    mock_plot.assert_called_once()


@pytest.mark.anyio
async def test_fetch_batter_zone_empty_raises() -> None:
    with (
        patch("bigleague.statcast_season", return_value=pl.DataFrame()),
        pytest.raises(ValueError, match="No Statcast batter data"),
    ):
        await fetch_batter_zone(123456, 2024, "Test Batter")


@pytest.mark.anyio
async def test_fetch_matchup_zone(mock_statcast_df: pl.DataFrame) -> None:
    # Batter season frame must contain a `pitcher` column carrying the id.
    df = mock_statcast_df.with_columns(pl.lit(999).alias("pitcher"))
    with (
        patch("bigleague.statcast_season", return_value=df),
        patch("bigleague.plots.matchup_zone", return_value=PNG) as mock_plot,
    ):
        result = await fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")

    _assert_png_buffer(result)
    mock_plot.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_spray_chart
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_spray_chart_success(mock_statcast_df: pl.DataFrame) -> None:
    with (
        patch("bigleague.statcast_season", return_value=mock_statcast_df),
        patch("statcast_plots._normalize_stadium", return_value="generic"),
        patch("bigleague.plots.spray_chart", return_value=PNG) as mock_spray,
    ):
        result = await fetch_spray_chart(123456, 2024, "Test Player", "generic")

    _assert_png_buffer(result)
    mock_spray.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_stadium_info
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_stadium_info_success() -> None:
    meta = {
        "name": "Comerica Park",
        "location": "Detroit, MI",
        "lf": 345,
        "cf": 420,
        "rf": 330,
    }
    with (
        patch("statcast_plots._normalize_stadium", return_value="tigers"),
        patch("statcast_plots._stadium_metadata", return_value=meta),
        patch("bigleague.plots.stadium_outline", return_value=PNG) as mock_plot,
    ):
        result = await fetch_stadium_info("tigers")

    assert result["name"] == "Comerica Park"
    assert result["location"] == "Detroit, MI"
    assert isinstance(result["image"], io.BytesIO)
    assert result["image"].read() == PNG
    mock_plot.assert_called_once()


@pytest.mark.anyio
async def test_fetch_stadium_info_unknown_raises() -> None:
    with (
        patch("statcast_plots._normalize_stadium", return_value="generic"),
        pytest.raises(ValueError, match="Unknown team/stadium"),
    ):
        await fetch_stadium_info("wrong_team")


# ---------------------------------------------------------------------------
# Render-failure / timeout / edge paths for /spraychart, /hotzones,
# /stadium, /matchupzone
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fetch_spray_chart_no_batted_balls_raises(mock_statcast_df: pl.DataFrame) -> None:
    """bigleague's spray_chart raises ValueError when no batted-ball coords
    remain; the facade re-raises a ValueError."""
    with (
        patch("bigleague.statcast_season", return_value=mock_statcast_df),
        patch("statcast_plots._normalize_stadium", return_value="generic"),
        patch("bigleague.plots.spray_chart", side_effect=ValueError("no batted balls")),
        pytest.raises(ValueError, match="No batted-ball events with coordinates"),
    ):
        await fetch_spray_chart(123456, 2024, "Test Player", "generic")


@pytest.mark.anyio
async def test_fetch_spray_chart_empty_data_raises() -> None:
    with (
        patch("bigleague.statcast_season", return_value=pl.DataFrame()),
        pytest.raises(ValueError, match="No Statcast data for batter_id"),
    ):
        await fetch_spray_chart(123456, 2024, "Test Player", "generic")


@pytest.mark.anyio
async def test_fetch_spray_chart_network_timeout_propagates() -> None:
    """statcast_season timing out (network) bubbles up — not swallowed."""
    with (
        patch("bigleague.statcast_season", side_effect=TimeoutError("savant slow")),
        pytest.raises(TimeoutError, match="savant slow"),
    ):
        await fetch_spray_chart(123456, 2024, "Test Player", "generic")


@pytest.mark.anyio
async def test_fetch_hotzones_network_timeout_propagates() -> None:
    with (
        patch("bigleague.statcast_season", side_effect=TimeoutError("savant slow")),
        pytest.raises(TimeoutError, match="savant slow"),
    ):
        await fetch_hitter_hotzones(123456, 2024, "Test Player")


@pytest.mark.anyio
async def test_fetch_stadium_info_plot_raises_propagates() -> None:
    """If bigleague's renderer errors, surface it (don't return a partial dict)."""
    meta = {"name": "Comerica Park", "location": "Detroit, MI", "lf": 345, "cf": 420, "rf": 330}
    with (
        patch("statcast_plots._normalize_stadium", return_value="tigers"),
        patch("statcast_plots._stadium_metadata", return_value=meta),
        patch("bigleague.plots.stadium_outline", side_effect=RuntimeError("matplotlib boom")),
        pytest.raises(RuntimeError, match="matplotlib boom"),
    ):
        await fetch_stadium_info("tigers")


@pytest.mark.anyio
async def test_fetch_matchup_zone_pitcher_never_faced_batter_raises(
    mock_statcast_df: pl.DataFrame,
) -> None:
    """Batter has data, but none of it is from the queried pitcher."""
    df = mock_statcast_df.with_columns(pl.lit(111).alias("pitcher"))
    with (
        patch("bigleague.statcast_season", return_value=df),
        pytest.raises(ValueError, match="No pitches found from pitcher 999"),
    ):
        await fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")


@pytest.mark.anyio
async def test_fetch_matchup_zone_empty_batter_data_raises() -> None:
    with (
        patch("bigleague.statcast_season", return_value=pl.DataFrame()),
        pytest.raises(ValueError, match="No Statcast data for batter_id"),
    ):
        await fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")


@pytest.mark.anyio
async def test_fetch_matchup_zone_network_timeout_propagates() -> None:
    with (
        patch("bigleague.statcast_season", side_effect=TimeoutError("savant slow")),
        pytest.raises(TimeoutError, match="savant slow"),
    ):
        await fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")
