"""
tests/conftest.py — VCR configuration for the tests/ directory.

cassette_library_dir points to tests/cassettes/ (alongside this file).
match_on excludes 'query' so date params (startDate, endDate, date=) in
MLB Stats API URLs don't cause cassette mismatches when tests run on
different days than when cassettes were recorded.

To regenerate all cassettes against the live API:
    uv run pytest tests/test_mlb_api_vcr.py --record-mode all
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "record_mode": "none",
        "cassette_library_dir": str(Path(__file__).parent / "cassettes"),
        "filter_headers": ["User-Agent", "Accept-Encoding", "Accept", "Connection"],
        # Exclude query string — date params change each run
        "match_on": ["method", "scheme", "host", "port", "path"],
    }
