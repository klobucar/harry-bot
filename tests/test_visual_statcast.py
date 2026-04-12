"""
tests/test_visual_statcast.py — Unit tests for visual plotting and data helpers.

Mocks pybaseball network calls and matplotlib figure creation.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from matplotlib.figure import Figure as RealFigure

import statcast
from statcast import (
    fetch_batter_zone,
    fetch_hitter_hotzones,
    fetch_matchup_zone,
    fetch_pitch_arsenal,
    fetch_pitcher_zone,
    fetch_schedule,
    fetch_spray_chart,
    fetch_stadium_info,
    fetch_standings,
    fetch_year_fangraphs,
)


@pytest.fixture(autouse=True)
def setup_statcast_globals():
    """Ensure statcast globals are not None for patching, even if _init_pybaseball is skipped."""
    # We set these on the module directly so they are available for both
    # patching and for the code's own use (like isinstance checks).
    old_fig = statcast.Figure
    old_plotting = statcast.plotting
    old_plt = statcast.plt

    statcast.Figure = RealFigure
    statcast.plotting = MagicMock()
    statcast.plt = MagicMock()

    with patch("statcast._init_pybaseball"):
        yield

    statcast.Figure = old_fig
    statcast.plotting = old_plotting
    statcast.plt = old_plt


@pytest.fixture
def mock_statcast_df() -> pd.DataFrame:
    """Return a minimal Statcast-shaped DataFrame."""
    return pd.DataFrame(
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


# ---------------------------------------------------------------------------
# fetch_hitter_hotzones
# ---------------------------------------------------------------------------


def test_fetch_hitter_hotzones_success(mock_statcast_df: pd.DataFrame) -> None:
    # Setup mock data for zones 1-9
    rows = []
    for z in range(1, 10):
        # 1 hit, 1 out per zone = .500 BA
        rows.append({"zone": float(z), "events": "single"})
        rows.append({"zone": float(z), "events": "field_out"})

    df = pd.DataFrame(rows)

    # We use a real Figure but mock savefig.
    # We DON'T patch statcast.Figure here because it's already set to RealFigure in the fixture.
    # If we need to capture the savefig, we can patch the real Figure's method.
    with (
        patch("statcast.statcast_batter", return_value=df),
        patch.object(RealFigure, "savefig"),
    ):
        result = fetch_hitter_hotzones(123456, 2024, "Test Player")

    assert isinstance(result, io.BytesIO)


def test_fetch_hitter_hotzones_empty_raises() -> None:
    with (
        patch("statcast.statcast_batter", return_value=pd.DataFrame()),
        pytest.raises(ValueError, match="No Statcast batter data"),
    ):
        fetch_hitter_hotzones(123456, 2024, "Test Player")


def test_fetch_hitter_hotzones_no_zone_data_raises() -> None:
    df = pd.DataFrame([{"zone": None, "events": "single"}])
    with (
        patch("statcast.statcast_batter", return_value=df),
        pytest.raises(ValueError, match="No pitches recorded in the strike zone"),
    ):
        fetch_hitter_hotzones(123456, 2024, "Test Player")


# ---------------------------------------------------------------------------
# Standard strike zone plotters
# ---------------------------------------------------------------------------


def test_fetch_pitcher_zone(mock_statcast_df: pd.DataFrame) -> None:
    real_fig = RealFigure()
    with (
        patch("statcast.statcast_pitcher", return_value=mock_statcast_df),
        patch.object(statcast.plotting, "plot_strike_zone") as mock_plot,
        patch.object(real_fig, "savefig"),
    ):
        mock_ax = MagicMock()
        mock_ax.get_figure.return_value = real_fig
        mock_plot.return_value = mock_ax

        result = fetch_pitcher_zone(123456, 2024, "Test Pitcher")
        assert isinstance(result, io.BytesIO)
        mock_plot.assert_called_once()


def test_fetch_batter_zone(mock_statcast_df: pd.DataFrame) -> None:
    real_fig = RealFigure()
    with (
        patch("statcast.statcast_batter", return_value=mock_statcast_df),
        patch.object(statcast.plotting, "plot_strike_zone") as mock_plot,
        patch.object(real_fig, "savefig"),
    ):
        mock_ax = MagicMock()
        mock_ax.get_figure.return_value = real_fig
        mock_plot.return_value = mock_ax

        result = fetch_batter_zone(123456, 2024, "Test Batter")
        assert isinstance(result, io.BytesIO)
        mock_plot.assert_called_once()


def test_fetch_matchup_zone(mock_statcast_df: pd.DataFrame) -> None:
    # Batter data must contain the pitcher_id
    mock_statcast_df["pitcher"] = 999
    real_fig = RealFigure()

    with (
        patch("statcast.statcast_batter", return_value=mock_statcast_df),
        patch.object(statcast.plotting, "plot_strike_zone") as mock_plot,
        patch.object(real_fig, "savefig"),
    ):
        mock_ax = MagicMock()
        mock_ax.get_figure.return_value = real_fig
        mock_plot.return_value = mock_ax

        result = fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")
        assert isinstance(result, io.BytesIO)
        mock_plot.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_spray_chart
# ---------------------------------------------------------------------------


def test_fetch_spray_chart_success(mock_statcast_df: pd.DataFrame) -> None:
    real_fig = RealFigure()
    with (
        patch("statcast.statcast_batter", return_value=mock_statcast_df),
        patch.object(statcast.plotting, "spraychart") as mock_spray,
        patch.object(real_fig, "savefig"),
    ):
        mock_ax = MagicMock()
        mock_ax.get_figure.return_value = real_fig
        mock_spray.return_value = mock_ax

        result = fetch_spray_chart(123456, 2024, "Test Player", "generic")
        assert isinstance(result, io.BytesIO)
        mock_spray.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_pitch_arsenal
# ---------------------------------------------------------------------------


def test_fetch_pitch_arsenal_returns_dict() -> None:
    # Statcast_pitcher_pitch_arsenal is called 3 times: speed, spin, usage
    df = pd.DataFrame(
        [
            {"pitcher": 123456, "ff_avg_speed": 95.2, "sl_avg_speed": 85.1},
        ]
    )
    spin_df = pd.DataFrame(
        [
            {"pitcher": 123456, "ff_avg_spin": 2400, "sl_avg_spin": 2600},
        ]
    )
    usage_df = pd.DataFrame(
        [
            {"pitcher": 123456, "n_ff": 100, "n_sl": 50},
        ]
    )

    with patch("statcast.statcast_pitcher_pitch_arsenal", side_effect=[df, spin_df, usage_df]):
        result = fetch_pitch_arsenal(123456, 2024)

    assert len(result) == 2
    # Result uses uppercase pitch names as keys (from prefix.upper())
    assert any(p["pitch"] == "FF" for p in result)


def test_fetch_pitch_arsenal_empty_raises() -> None:
    with (
        patch("statcast.statcast_pitcher_pitch_arsenal", return_value=pd.DataFrame()),
        pytest.raises(ValueError, match="No arsenal data"),
    ):
        fetch_pitch_arsenal(123456, 2024)


# ---------------------------------------------------------------------------
# fetch_standings
# ---------------------------------------------------------------------------


def test_fetch_standings_success() -> None:
    # standings() returns a list of DataFrames
    df_al_central = pd.DataFrame(
        [
            {"Tm": "DET", "W": 86, "L": 76, "W-L%": 0.531},
            {"Tm": "CLE", "W": 92, "L": 70, "W-L%": 0.568},
        ]
    )

    with patch("statcast.standings", return_value=[df_al_central]):
        result = fetch_standings(2024)

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], tuple)


def test_fetch_standings_empty_raises() -> None:
    with (
        patch("statcast.standings", return_value=[]),
        pytest.raises(ValueError, match="No standings data"),
    ):
        fetch_standings(2024)


# ---------------------------------------------------------------------------
# fetch_schedule
# ---------------------------------------------------------------------------


def test_fetch_schedule_success() -> None:
    # schedule_and_record() returns a DataFrame
    # Need more rows to avoid index out of bounds if it slices
    df = pd.DataFrame(
        [
            {
                "Date": "Friday, Mar 28",
                "Opp": "CLE",
                "W/L": "W",
                "R": 4,
                "RA": 1,
                "Boxscore": "box",
                "Attendance": 1000,
            },
        ]
        * 10
    )

    with patch("statcast.schedule_and_record", return_value=df):
        result = fetch_schedule("DET", 2024)

    assert isinstance(result, tuple)
    assert len(result) == 2


def test_fetch_schedule_empty_raises() -> None:
    with (
        patch("statcast.schedule_and_record", return_value=pd.DataFrame()),
        pytest.raises(ValueError, match="No schedule data"),
    ):
        fetch_schedule("DET", 2024)


# ---------------------------------------------------------------------------
# fetch_year_fangraphs
# ---------------------------------------------------------------------------


def test_fetch_year_fangraphs_pitcher() -> None:
    df = pd.DataFrame([{"Name": "Tarik Skubal", "ERA": 2.39}])
    with (
        patch("statcast.fg_pitching_data", return_value=df),
        patch("statcast.fg_batting_data", return_value=pd.DataFrame()),
    ):
        result = fetch_year_fangraphs(2024, "pitcher", "Tarik", "Skubal")

    assert isinstance(result, pd.DataFrame)
    assert result.iloc[0]["ERA"] == 2.39


def test_fetch_year_fangraphs_batter() -> None:
    df = pd.DataFrame([{"Name": "Riley Greene", "AVG": 0.280}])
    with (
        patch("statcast.fg_pitching_data", return_value=pd.DataFrame()),
        patch("statcast.fg_batting_data", return_value=df),
    ):
        result = fetch_year_fangraphs(2024, "batter", "Riley", "Greene")

    assert isinstance(result, pd.DataFrame)
    assert result.iloc[0]["AVG"] == 0.280


def test_fetch_year_fangraphs_not_found_raises() -> None:
    with (
        patch("statcast.fg_pitching_data", return_value=pd.DataFrame()),
        patch("statcast.fg_batting_data", return_value=pd.DataFrame()),
    ):
        result = fetch_year_fangraphs(2024, "pitcher", "nobody", "here")
        assert result is None


# ---------------------------------------------------------------------------
# fetch_stadium_info
# ---------------------------------------------------------------------------


def test_fetch_stadium_info_success() -> None:
    real_fig = RealFigure()
    mock_df = pd.DataFrame(
        [{"team": "detroit_tigers", "name": "Comerica Park", "location": "Detroit, MI"}]
    )

    with (
        patch("statcast._normalize_stadium", return_value="detroit_tigers"),
        patch("statcast.pd.read_csv", return_value=mock_df),
        patch.object(statcast.plotting, "plot_stadium") as mock_plot,
        patch.object(real_fig, "savefig"),
    ):
        mock_ax = MagicMock()
        mock_ax.get_figure.return_value = real_fig
        mock_plot.return_value = mock_ax

        result = fetch_stadium_info("tigers")

    assert result["name"] == "Comerica Park"
    assert result["location"] == "Detroit, MI"
    assert isinstance(result["image"], io.BytesIO)
    mock_plot.assert_called_once_with("detroit_tigers")


def test_fetch_stadium_info_unknown_raises() -> None:
    with (
        patch("statcast._normalize_stadium", return_value="generic"),
        pytest.raises(ValueError, match="Unknown team/stadium"),
    ):
        fetch_stadium_info("wrong_team")
