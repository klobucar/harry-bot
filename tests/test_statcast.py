"""
tests/test_statcast.py — Unit tests for statcast.py pure helpers.

All pybaseball network calls are mocked. No internet required.
Run with: python -m pytest tests/ -v
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from persona import harry_error
from statcast import (
    AB_EVENTS,
    HIT_EVENTS,
    compute_matchup_stats,
    fetch_fg_leaderboard,
    resolve_player_id,
    season_range,
)

# ---------------------------------------------------------------------------
# season_range
# ---------------------------------------------------------------------------


class TestSeasonRange:
    def test_start_date(self) -> None:
        start, _ = season_range(2023)
        assert start == "2023-03-01"

    def test_end_date(self) -> None:
        _, end = season_range(2023)
        assert end == "2023-11-30"

    def test_year_is_formatted(self) -> None:
        start, end = season_range(2019)
        assert start.startswith("2019")
        assert end.startswith("2019")


# ---------------------------------------------------------------------------
# resolve_player_id
# ---------------------------------------------------------------------------


class TestResolvePlayerId:
    def test_returns_none_for_empty_result(self) -> None:
        with patch("statcast.playerid_lookup", return_value=pd.DataFrame()):
            result = resolve_player_id("nolan", "ryan")
        assert result is None

    def test_returns_none_when_no_mlbam_column(self) -> None:
        df = pd.DataFrame({"key_mlbam": [None, None]})
        with patch("statcast.playerid_lookup", return_value=df):
            result = resolve_player_id("nolan", "ryan")
        assert result is None

    def test_returns_correct_id(self) -> None:
        df = pd.DataFrame({"key_mlbam": [121250]})
        with patch("statcast.playerid_lookup", return_value=df):
            result = resolve_player_id("nolan", "ryan")
        assert result == 121250

    def test_returns_first_match_on_multiple_rows(self) -> None:
        df = pd.DataFrame({"key_mlbam": [111, 222, 333]})
        with patch("statcast.playerid_lookup", return_value=df):
            result = resolve_player_id("pedro", "martinez")
        assert result == 111

    def test_passes_args_in_correct_order(self) -> None:
        """playerid_lookup expects (last, first, fuzzy=True) — verify the call."""
        with patch("statcast.playerid_lookup", return_value=pd.DataFrame()) as mock_lookup:
            resolve_player_id("nolan", "ryan")
        mock_lookup.assert_called_once_with("ryan", "nolan", fuzzy=True)


# ---------------------------------------------------------------------------
# AB_EVENTS / HIT_EVENTS constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_ab_events_is_frozenset(self) -> None:
        assert isinstance(AB_EVENTS, frozenset)

    def test_hit_events_subset_of_ab_events(self) -> None:
        assert HIT_EVENTS <= AB_EVENTS

    def test_strikeout_in_ab_events(self) -> None:
        assert "strikeout" in AB_EVENTS

    def test_home_run_in_hit_events(self) -> None:
        assert "home_run" in HIT_EVENTS

    def test_walk_not_in_ab_events(self) -> None:
        # walks don't count as at-bats
        assert "walk" not in AB_EVENTS


# ---------------------------------------------------------------------------
# compute_matchup_stats
# ---------------------------------------------------------------------------


def _make_matchup_df(events: list[str], pitcher_id: int = 99) -> pd.DataFrame:
    """Build a minimal StatCast-shaped DataFrame for testing."""
    return pd.DataFrame({"pitcher": [pitcher_id] * len(events), "events": events})


class TestComputeMatchupStats:
    def test_raises_on_empty_batter_data(self) -> None:
        with (
            patch("statcast.statcast_batter", return_value=pd.DataFrame()),
            pytest.raises(ValueError, match="No Statcast data"),
        ):
            compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)

    def test_raises_when_pitcher_never_faced_batter(self) -> None:
        df = _make_matchup_df(["single"], pitcher_id=1)
        with (
            patch("statcast.statcast_batter", return_value=df),
            pytest.raises(ValueError, match="No plate appearances"),
        ):
            compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)

    def test_batting_average_calculation(self) -> None:
        # 1 single + 1 strikeout = 0.500 AVG
        df = _make_matchup_df(["single", "strikeout"])
        with patch("statcast.statcast_batter", return_value=df):
            stats = compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["batting_avg"] == pytest.approx(0.5)

    def test_zero_avg_on_all_strikeouts(self) -> None:
        df = _make_matchup_df(["strikeout", "strikeout", "strikeout"])
        with patch("statcast.statcast_batter", return_value=df):
            stats = compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["batting_avg"] == 0.0
        assert stats["strikeouts"] == 3

    def test_pa_vs_ab_difference(self) -> None:
        # walks are PA but not AB; single is both
        df = _make_matchup_df(["walk", "single"])
        with patch("statcast.statcast_batter", return_value=df):
            stats = compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["pa"] == 2
        assert stats["ab"] == 1  # walk excluded
        assert stats["hits"] == 1

    def test_hit_count(self) -> None:
        df = _make_matchup_df(["single", "double", "triple", "home_run", "strikeout"])
        with patch("statcast.statcast_batter", return_value=df):
            stats = compute_matchup_stats(pitcher_id=99, batter_id=1, year=2023)
        assert stats["hits"] == 4


# ---------------------------------------------------------------------------
# persona (quick smoke test — no mocking needed)
# ---------------------------------------------------------------------------


class TestPersona:
    def test_harry_error_returns_string(self) -> None:
        msg = harry_error()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_harry_error_with_extra_contains_detail(self) -> None:
        msg = harry_error("connection refused")
        assert "connection refused" in msg


# ---------------------------------------------------------------------------
# fetch_fg_leaderboard (JSON API + HTML stripping)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class TestFetchFgLeaderboard:
    def test_strips_html_from_name_and_team(self) -> None:
        payload = {
            "data": [
                {
                    "Name": '<a href="statss.aspx?playerid=1">Aaron Judge</a>',
                    "Team": '<a href="leaders.aspx?team=9">NYY</a>',
                    "HR": 58.0,
                }
            ]
        }
        with patch("curl_cffi.requests.get", return_value=_FakeResp(payload)) as mock_get:
            df = fetch_fg_leaderboard(2024, "bat")
        assert df.iloc[0]["Name"] == "Aaron Judge"
        assert df.iloc[0]["Team"] == "NYY"
        # ensure impersonation is used, or FanGraphs 403s
        assert mock_get.call_args.kwargs.get("impersonate") == "chrome"

    def test_empty_data_returns_empty_df(self) -> None:
        with patch("curl_cffi.requests.get", return_value=_FakeResp({"data": []})):
            df = fetch_fg_leaderboard(2099, "pit")
        assert df.empty

    def test_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValueError, match="kind must be"):
            fetch_fg_leaderboard(2024, "fielding")  # type: ignore[arg-type]

    def test_sends_pit_stat_param_for_pitcher(self) -> None:
        with patch("curl_cffi.requests.get", return_value=_FakeResp({"data": []})) as mock_get:
            fetch_fg_leaderboard(2024, "pit")
        assert mock_get.call_args.kwargs["params"]["stats"] == "pit"
        assert mock_get.call_args.kwargs["params"]["season"] == 2024


# ---------------------------------------------------------------------------
# /schedule CoW regression (pybaseball 2.2.7 x pandas 2.x)
# ---------------------------------------------------------------------------


class TestScheduleUnknownAttendanceRegression:
    """
    Regression for the /schedule bug where pybaseball's process_schedule does
    an inplace replace that silently no-ops under pandas 2.x Copy-on-Write,
    leaving 'Unknown' strings in Attendance and making make_numeric's
    astype(float) raise. statcast._patch_schedule_make_numeric replaces
    make_numeric with a CoW-safe version; this test verifies it handles the
    shape of data pybaseball actually hands it.
    """

    def test_unknown_attendance_becomes_nan_and_astype_float_succeeds(self) -> None:
        import numpy as np

        import statcast

        statcast._init_pybaseball()  # applies the patch

        import pybaseball.team_results as tr

        df = pd.DataFrame(
            {
                "Attendance": ["45,000", "Unknown", "32,500", "Unknown"],
                "R": [3.0, 1.0, 7.0, 2.0],
                "RA": [2.0, 4.0, 3.0, 5.0],
                "Inn": [9.0, 9.0, 10.0, 9.0],
                "Rank": [1.0, 1.0, 1.0, 2.0],
            }
        )

        result = tr.make_numeric(df.copy())

        assert result["Attendance"].dtype == np.float64
        assert result.loc[0, "Attendance"] == 45000.0
        assert result.loc[2, "Attendance"] == 32500.0
        assert pd.isna(result.loc[1, "Attendance"])
        assert pd.isna(result.loc[3, "Attendance"])

    def test_all_na_attendance_column_still_casts(self) -> None:
        """If Attendance is entirely empty, make_numeric should fill with NaN."""
        import statcast

        statcast._init_pybaseball()

        import pybaseball.team_results as tr

        df = pd.DataFrame(
            {
                "Attendance": [None, None, None],
                "R": [1.0, 2.0, 3.0],
                "RA": [0.0, 1.0, 2.0],
                "Inn": [9.0, 9.0, 9.0],
                "Rank": [1.0, 1.0, 1.0],
            }
        )
        result = tr.make_numeric(df.copy())
        assert result["Attendance"].isna().all()
