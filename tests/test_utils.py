"""
tests/test_utils.py — Tests for utils.py year validators.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

from utils import (
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


class TestCurrentSeason:
    def test_january_returns_previous_year(self) -> None:
        """Opening Day hasn't happened yet — default to last season."""
        assert current_season(datetime.date(2026, 1, 15)) == 2025

    def test_february_returns_previous_year(self) -> None:
        assert current_season(datetime.date(2026, 2, 28)) == 2025

    def test_march_returns_previous_year(self) -> None:
        """Even late March — Opening Day floats, April 1 is the clean cutoff."""
        assert current_season(datetime.date(2026, 3, 31)) == 2025

    def test_april_first_returns_current_year(self) -> None:
        """April 1 is the bright-line switch — every team has played by now."""
        assert current_season(datetime.date(2026, 4, 1)) == 2026

    def test_midseason_returns_current_year(self) -> None:
        assert current_season(datetime.date(2026, 7, 15)) == 2026

    def test_october_returns_current_year(self) -> None:
        """Postseason still counts as the current year's data."""
        assert current_season(datetime.date(2026, 10, 30)) == 2026

    def test_december_returns_current_year(self) -> None:
        """Off-season December — still last year's season data is current."""
        assert current_season(datetime.date(2026, 12, 31)) == 2026

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
