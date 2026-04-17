"""
tests/test_utils.py — Tests for utils.py year validators.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

from utils import (
    _last_thursday_of_march,
    current_season,
    validate_fangraphs_year,
    validate_statcast_year,
    validate_year_range,
)


class TestValidateStatcastYear:
    def test_valid_year_returns_none(self) -> None:
        assert validate_statcast_year(2023) is None

    def test_min_boundary_is_valid(self) -> None:
        assert validate_statcast_year(2015) is None

    def test_before_statcast_era_returns_error(self) -> None:
        err = validate_statcast_year(2014)
        assert err is not None
        assert "2015" in err

    def test_ancient_year_returns_error(self) -> None:
        assert validate_statcast_year(1990) is not None

    def test_future_year_returns_error(self) -> None:
        with patch("utils.current_year", return_value=2025):
            err = validate_statcast_year(2026)
        assert err is not None
        assert "future" in err.lower() or "2026" in err

    def test_current_year_is_valid(self) -> None:
        with patch("utils.current_year", return_value=2025):
            assert validate_statcast_year(2025) is None


class TestValidateFangraphsYear:
    def test_valid_year_returns_none(self) -> None:
        assert validate_fangraphs_year(2023) is None

    def test_min_boundary_is_valid(self) -> None:
        assert validate_fangraphs_year(2002) is None

    def test_before_fangraphs_era_returns_error(self) -> None:
        err = validate_fangraphs_year(2001)
        assert err is not None
        assert "2002" in err

    def test_future_year_returns_error(self) -> None:
        with patch("utils.current_year", return_value=2025):
            err = validate_fangraphs_year(2030)
        assert err is not None

    def test_statcast_year_valid_for_fangraphs(self) -> None:
        # 2015 is valid for Statcast — also valid for FanGraphs
        assert validate_fangraphs_year(2015) is None


class TestLastThursdayOfMarch:
    """Spot-check the Opening Day resolver against known MLB seasons."""

    def test_2024(self) -> None:
        assert _last_thursday_of_march(2024) == datetime.date(2024, 3, 28)

    def test_2023(self) -> None:
        assert _last_thursday_of_march(2023) == datetime.date(2023, 3, 30)

    def test_2025(self) -> None:
        assert _last_thursday_of_march(2025) == datetime.date(2025, 3, 27)

    def test_2026(self) -> None:
        assert _last_thursday_of_march(2026) == datetime.date(2026, 3, 26)

    def test_result_is_always_a_thursday(self) -> None:
        for year in range(2018, 2040):
            assert _last_thursday_of_march(year).weekday() == 3

    def test_result_is_always_in_march(self) -> None:
        for year in range(2018, 2040):
            d = _last_thursday_of_march(year)
            assert d.month == 3
            # Must be in the final week — at least March 25
            assert d.day >= 25


class TestCurrentSeason:
    def test_january_returns_previous_year(self) -> None:
        """Opening Day hasn't happened yet — default to last season."""
        assert current_season(datetime.date(2026, 1, 15)) == 2025

    def test_february_returns_previous_year(self) -> None:
        assert current_season(datetime.date(2026, 2, 28)) == 2025

    def test_early_march_returns_previous_year(self) -> None:
        """Early March is well before Opening Day."""
        assert current_season(datetime.date(2026, 3, 10)) == 2025

    def test_day_before_opening_day_returns_previous_year(self) -> None:
        """Tuesday before Opening Day 2026 (March 26) — still 2025's data."""
        assert current_season(datetime.date(2026, 3, 25)) == 2025

    def test_opening_day_returns_current_year(self) -> None:
        """The bright-line switch — Opening Day itself counts as the current season."""
        assert current_season(datetime.date(2026, 3, 26)) == 2026

    def test_day_after_opening_day_returns_current_year(self) -> None:
        assert current_season(datetime.date(2026, 3, 27)) == 2026

    def test_midseason_returns_current_year(self) -> None:
        assert current_season(datetime.date(2026, 7, 15)) == 2026

    def test_october_returns_current_year(self) -> None:
        """Postseason still counts as the current year's data."""
        assert current_season(datetime.date(2026, 10, 30)) == 2026

    def test_december_returns_current_year(self) -> None:
        """Off-season December — still counts as the most recent season."""
        assert current_season(datetime.date(2026, 12, 31)) == 2026

    def test_2024_opening_day(self) -> None:
        """Regression: real 2024 Opening Day was March 28."""
        assert current_season(datetime.date(2024, 3, 27)) == 2023
        assert current_season(datetime.date(2024, 3, 28)) == 2024

    def test_no_argument_uses_today(self) -> None:
        """Default-argument version uses date.today() — smoke test only."""
        result = current_season()
        expected_year = datetime.date.today().year
        assert result in (expected_year, expected_year - 1)


class TestValidateYearRange:
    def test_valid_range(self) -> None:
        assert validate_year_range(2010, 2023) is None

    def test_start_equals_end(self) -> None:
        assert validate_year_range(2020, 2020) is None

    def test_start_after_end_returns_error(self) -> None:
        err = validate_year_range(2023, 2020)
        assert err is not None

    def test_start_before_min_returns_error(self) -> None:
        err = validate_year_range(1990, 2023, min_year=2002)
        assert err is not None

    def test_end_in_future_returns_error(self) -> None:
        with patch("utils.current_year", return_value=2025):
            err = validate_year_range(2020, 2030)
        assert err is not None
