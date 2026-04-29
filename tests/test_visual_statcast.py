"""
tests/test_visual_statcast.py — Unit tests for visual plotting and data helpers.

Mocks pybaseball network calls and matplotlib figure creation.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from matplotlib.figure import Figure as RealFigure

import statcast_patch
import statcast_plots  # noqa: F401  — registers module so patch("statcast_plots.X") works
from fangraphs import fetch_year_fangraphs

# Capture the real _init_pybaseball before the autouse fixture below replaces
# it with a MagicMock. The UA-scope regression tests need to actually run the
# real init to verify that requests.Session.request isn't patched globally.
_REAL_INIT_PYBASEBALL = statcast_patch._init_pybaseball
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
)


@pytest.fixture(autouse=True)
def setup_statcast_globals():
    """
    Set up patched matplotlib + plotting on statcast_patch so the helpers in
    statcast_plots see them (they look up via statcast_patch.X attribute access).
    """
    old_fig = statcast_patch.Figure
    old_plotting = statcast_patch.plotting
    old_plt = statcast_patch.plt

    statcast_patch.Figure = RealFigure
    statcast_patch.plotting = MagicMock()
    statcast_patch.plt = MagicMock()

    with patch("statcast_patch._init_pybaseball"):
        yield

    statcast_patch.Figure = old_fig
    statcast_patch.plotting = old_plotting
    statcast_patch.plt = old_plt


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

    with (
        patch("statcast_patch.statcast_batter", return_value=df),
        patch.object(RealFigure, "savefig"),
    ):
        result = fetch_hitter_hotzones(123456, 2024, "Test Player")

    assert isinstance(result, io.BytesIO)


def test_fetch_hitter_hotzones_empty_raises() -> None:
    with (
        patch("statcast_patch.statcast_batter", return_value=pd.DataFrame()),
        pytest.raises(ValueError, match="No Statcast batter data"),
    ):
        fetch_hitter_hotzones(123456, 2024, "Test Player")


def test_fetch_hitter_hotzones_no_zone_data_raises() -> None:
    df = pd.DataFrame([{"zone": None, "events": "single"}])
    with (
        patch("statcast_patch.statcast_batter", return_value=df),
        pytest.raises(ValueError, match="No pitches recorded in the strike zone"),
    ):
        fetch_hitter_hotzones(123456, 2024, "Test Player")


# ---------------------------------------------------------------------------
# Standard strike zone plotters
# ---------------------------------------------------------------------------


def test_fetch_pitcher_zone(mock_statcast_df: pd.DataFrame) -> None:
    real_fig = RealFigure()
    with (
        patch("statcast_patch.statcast_pitcher", return_value=mock_statcast_df),
        patch.object(statcast_patch.plotting, "plot_strike_zone") as mock_plot,
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
        patch("statcast_patch.statcast_batter", return_value=mock_statcast_df),
        patch.object(statcast_patch.plotting, "plot_strike_zone") as mock_plot,
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
        patch("statcast_patch.statcast_batter", return_value=mock_statcast_df),
        patch.object(statcast_patch.plotting, "plot_strike_zone") as mock_plot,
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
        patch("statcast_patch.statcast_batter", return_value=mock_statcast_df),
        patch.object(statcast_patch.plotting, "spraychart") as mock_spray,
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

    with patch(
        "statcast_patch.statcast_pitcher_pitch_arsenal", side_effect=[df, spin_df, usage_df]
    ):
        result = fetch_pitch_arsenal(123456, 2024)

    assert len(result) == 2
    # Result uses uppercase pitch names as keys (from prefix.upper())
    assert any(p["pitch"] == "FF" for p in result)


def test_fetch_pitch_arsenal_empty_raises() -> None:
    with (
        patch("statcast_patch.statcast_pitcher_pitch_arsenal", return_value=pd.DataFrame()),
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

    with patch("statcast_patch.standings", return_value=[df_al_central]):
        result = fetch_standings(2024)

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], tuple)


def test_fetch_standings_empty_raises() -> None:
    with (
        patch("statcast_patch.standings", return_value=[]),
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

    with patch("statcast_patch.schedule_and_record", return_value=df):
        result = fetch_schedule("DET", 2024)

    assert isinstance(result, tuple)
    assert len(result) == 2


def test_fetch_schedule_empty_raises() -> None:
    with (
        patch("statcast_patch.schedule_and_record", return_value=pd.DataFrame()),
        pytest.raises(ValueError, match="No schedule data"),
    ):
        fetch_schedule("DET", 2024)


# ---------------------------------------------------------------------------
# fetch_year_fangraphs
# ---------------------------------------------------------------------------


def _fg_side(pit: pd.DataFrame | None = None, bat: pd.DataFrame | None = None):
    pit_df = pit if pit is not None else pd.DataFrame()
    bat_df = bat if bat is not None else pd.DataFrame()
    return lambda _year, kind, **_kw: pit_df if kind == "pit" else bat_df


def test_fetch_year_fangraphs_pitcher() -> None:
    df = pd.DataFrame([{"Name": "Tarik Skubal", "ERA": 2.39}])
    with patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side(pit=df)):
        result = fetch_year_fangraphs(2024, "pitcher", "Tarik", "Skubal")

    assert isinstance(result, pd.DataFrame)
    assert result.iloc[0]["ERA"] == 2.39


def test_fetch_year_fangraphs_batter() -> None:
    df = pd.DataFrame([{"Name": "Riley Greene", "AVG": 0.280}])
    with patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side(bat=df)):
        result = fetch_year_fangraphs(2024, "batter", "Riley", "Greene")

    assert isinstance(result, pd.DataFrame)
    assert result.iloc[0]["AVG"] == 0.280


def test_fetch_year_fangraphs_not_found_raises() -> None:
    with patch("fangraphs.fetch_fg_leaderboard", side_effect=_fg_side()):
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
        patch("statcast_plots._normalize_stadium", return_value="detroit_tigers"),
        patch("statcast_plots.pd.read_csv", return_value=mock_df),
        patch.object(statcast_patch.plotting, "plot_stadium") as mock_plot,
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
        patch("statcast_plots._normalize_stadium", return_value="generic"),
        pytest.raises(ValueError, match="Unknown team/stadium"),
    ):
        fetch_stadium_info("wrong_team")


# ---------------------------------------------------------------------------
# Render-failure / timeout / edge paths for /spraychart, /hotzones,
# /stadium, /matchupzone
# ---------------------------------------------------------------------------


def test_fetch_spray_chart_no_inplay_events_raises(mock_statcast_df: pd.DataFrame) -> None:
    """All rows are non-X (e.g. balls/strikes), so no batted-ball coords remain."""
    df = mock_statcast_df.copy()
    df["type"] = "B"  # non-in-play
    with (
        patch("statcast_patch.statcast_batter", return_value=df),
        pytest.raises(ValueError, match="No batted-ball events with coordinates"),
    ):
        fetch_spray_chart(123456, 2024, "Test Player", "generic")


def test_fetch_spray_chart_park_filter_empty_raises(mock_statcast_df: pd.DataFrame) -> None:
    """Batter has data but never played at the requested stadium."""
    df = mock_statcast_df.copy()
    df["home_team"] = "NYY"  # batter only ever played at Yankee Stadium
    with (
        patch("statcast_patch.statcast_batter", return_value=df),
        # Force the stadium to a known team (tigers → DET) so the home_team
        # filter actually runs and finds zero rows.
        patch("statcast_plots._normalize_stadium", return_value="tigers"),
        pytest.raises(ValueError, match="They may not have played there"),
    ):
        fetch_spray_chart(123456, 2024, "Test Player", "tigers")


def test_fetch_spray_chart_savefig_failure_still_closes_fig(
    mock_statcast_df: pd.DataFrame,
) -> None:
    """If savefig blows up mid-render, plt.close must still run (no fig leak)."""
    real_fig = RealFigure()
    with (
        patch("statcast_patch.statcast_batter", return_value=mock_statcast_df),
        patch.object(statcast_patch.plotting, "spraychart") as mock_spray,
        patch.object(real_fig, "savefig", side_effect=OSError("disk full")),
    ):
        mock_ax = MagicMock()
        mock_ax.get_figure.return_value = real_fig
        mock_spray.return_value = mock_ax

        with pytest.raises(OSError, match="disk full"):
            fetch_spray_chart(123456, 2024, "Test Player", "generic")

    # plt is a MagicMock from the autouse fixture; verify the cleanup ran.
    statcast_patch.plt.close.assert_called_with(real_fig)


def test_fetch_spray_chart_plotting_raises_propagates(
    mock_statcast_df: pd.DataFrame,
) -> None:
    """If pybaseball.spraychart itself raises (e.g. KeyError), surface it."""
    with (
        patch("statcast_patch.statcast_batter", return_value=mock_statcast_df),
        patch.object(statcast_patch.plotting, "spraychart", side_effect=KeyError("missing column")),
        pytest.raises(KeyError, match="missing column"),
    ):
        fetch_spray_chart(123456, 2024, "Test Player", "generic")


def test_fetch_spray_chart_network_timeout_propagates() -> None:
    """statcast_batter timing out (network) bubbles up — not swallowed."""
    with (
        patch("statcast_patch.statcast_batter", side_effect=TimeoutError("savant slow")),
        pytest.raises(TimeoutError, match="savant slow"),
    ):
        fetch_spray_chart(123456, 2024, "Test Player", "generic")


def test_fetch_hotzones_savefig_failure_still_closes_fig() -> None:
    """If savefig fails mid-render, plt.close must still run."""
    rows = []
    for z in range(1, 10):
        rows.append({"zone": float(z), "events": "single"})
        rows.append({"zone": float(z), "events": "field_out"})
    df = pd.DataFrame(rows)

    with (
        patch("statcast_patch.statcast_batter", return_value=df),
        patch.object(RealFigure, "savefig", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        fetch_hitter_hotzones(123456, 2024, "Test Player")

    statcast_patch.plt.close.assert_called()


def test_fetch_hotzones_network_timeout_propagates() -> None:
    with (
        patch("statcast_patch.statcast_batter", side_effect=TimeoutError("savant slow")),
        pytest.raises(TimeoutError, match="savant slow"),
    ):
        fetch_hitter_hotzones(123456, 2024, "Test Player")


def test_fetch_stadium_info_savefig_failure_still_closes_fig() -> None:
    real_fig = RealFigure()
    mock_df = pd.DataFrame([{"team": "tigers", "name": "Comerica Park", "location": "Detroit, MI"}])

    with (
        patch("statcast_plots._normalize_stadium", return_value="tigers"),
        patch("statcast_plots.pd.read_csv", return_value=mock_df),
        patch.object(statcast_patch.plotting, "plot_stadium") as mock_plot,
        patch.object(real_fig, "savefig", side_effect=OSError("disk full")),
    ):
        mock_ax = MagicMock()
        mock_ax.get_figure.return_value = real_fig
        mock_plot.return_value = mock_ax

        with pytest.raises(OSError, match="disk full"):
            fetch_stadium_info("tigers")

    statcast_patch.plt.close.assert_called_with(real_fig)


def test_fetch_stadium_info_plot_stadium_raises_propagates() -> None:
    """If pybaseball.plot_stadium errors, surface it (don't return a partial dict)."""
    mock_df = pd.DataFrame([{"team": "tigers", "name": "Comerica Park", "location": "Detroit, MI"}])
    with (
        patch("statcast_plots._normalize_stadium", return_value="tigers"),
        patch("statcast_plots.pd.read_csv", return_value=mock_df),
        patch.object(
            statcast_patch.plotting, "plot_stadium", side_effect=RuntimeError("matplotlib boom")
        ),
        pytest.raises(RuntimeError, match="matplotlib boom"),
    ):
        fetch_stadium_info("tigers")


def test_fetch_matchup_zone_pitcher_never_faced_batter_raises(
    mock_statcast_df: pd.DataFrame,
) -> None:
    """Batter has data, but none of it is from the queried pitcher."""
    df = mock_statcast_df.copy()
    df["pitcher"] = 111  # batter has data, but not against pitcher 999
    with (
        patch("statcast_patch.statcast_batter", return_value=df),
        pytest.raises(ValueError, match="No pitches found from pitcher 999"),
    ):
        fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")


def test_fetch_matchup_zone_empty_batter_data_raises() -> None:
    with (
        patch("statcast_patch.statcast_batter", return_value=pd.DataFrame()),
        pytest.raises(ValueError, match="No Statcast data for batter_id"),
    ):
        fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")


def test_fetch_matchup_zone_savefig_failure_still_closes_fig(
    mock_statcast_df: pd.DataFrame,
) -> None:
    df = mock_statcast_df.copy()
    df["pitcher"] = 999
    real_fig = RealFigure()

    with (
        patch("statcast_patch.statcast_batter", return_value=df),
        patch.object(statcast_patch.plotting, "plot_strike_zone") as mock_plot,
        patch.object(real_fig, "savefig", side_effect=OSError("disk full")),
    ):
        mock_ax = MagicMock()
        mock_ax.get_figure.return_value = real_fig
        mock_plot.return_value = mock_ax

        with pytest.raises(OSError, match="disk full"):
            fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")

    statcast_patch.plt.close.assert_called_with(real_fig)


def test_fetch_matchup_zone_network_timeout_propagates() -> None:
    with (
        patch("statcast_patch.statcast_batter", side_effect=TimeoutError("savant slow")),
        pytest.raises(TimeoutError, match="savant slow"),
    ):
        fetch_matchup_zone(999, 123456, 2024, "Pitcher", "Batter")


# ---------------------------------------------------------------------------
# UA-scope regression — make sure _init_pybaseball() doesn't bleed a
# Session.request monkeypatch into the rest of the process anymore.
# ---------------------------------------------------------------------------


def _force_real_init() -> None:
    """
    Run the *real* _init_pybaseball (the autouse fixture replaces it with a
    MagicMock). Reset the initialized flag so the body actually runs even
    if a prior test already triggered it.
    """
    old_flag = statcast_patch._pybaseball_initialized
    statcast_patch._pybaseball_initialized = False
    try:
        _REAL_INIT_PYBASEBALL()
    finally:
        statcast_patch._pybaseball_initialized = old_flag


def test_init_pybaseball_does_not_patch_requests_session_globally() -> None:
    """
    Regression: the old implementation patched requests.Session.request
    process-wide, which bled into discord.py / google-genai / curl_cffi
    fallbacks. Verify the post-init Session.request is the unmodified one.
    """
    import requests

    original_request = requests.Session.request
    _force_real_init()

    assert requests.Session.request is original_request, (
        "statcast_patch._init_pybaseball() patched requests.Session.request "
        "process-wide. It should patch only pybaseball's modules instead."
    )


def test_pybaseball_modules_get_ua_proxy_after_init() -> None:
    """The scoped patch replaces the requests reference in pybaseball.* only."""
    import sys

    _force_real_init()

    sb_mod = sys.modules["pybaseball.statcast_batter"]
    assert type(sb_mod.requests).__name__ == "_UAInjectingRequests", (
        f"Expected pybaseball.statcast_batter.requests to be the UA proxy, "
        f"got {type(sb_mod.requests).__name__}"
    )


def test_ua_proxy_injects_browser_user_agent() -> None:
    """The proxy injects the browser UA when no header is supplied."""
    import sys

    _force_real_init()

    sb_mod = sys.modules["pybaseball.statcast_batter"]
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> Any:
        captured["headers"] = kwargs.get("headers")
        return MagicMock(content=b"", raise_for_status=lambda: None)

    with patch.object(sb_mod.requests._real, "get", side_effect=fake_get):
        sb_mod.requests.get("https://example.test/foo")

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert "Chrome" in headers["User-Agent"], (
        f"Proxy did not inject browser UA: {headers['User-Agent']!r}"
    )


def test_ua_proxy_preserves_caller_supplied_user_agent() -> None:
    """If the caller passes a User-Agent, the proxy must not clobber it."""
    import sys

    _force_real_init()

    sb_mod = sys.modules["pybaseball.statcast_batter"]
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> Any:
        captured["headers"] = kwargs.get("headers")
        return MagicMock(content=b"", raise_for_status=lambda: None)

    with patch.object(sb_mod.requests._real, "get", side_effect=fake_get):
        sb_mod.requests.get("https://example.test/foo", headers={"User-Agent": "MyBot/1.0"})

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"] == "MyBot/1.0"
