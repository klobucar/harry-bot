"""
statcast_patch.py — Lazy pybaseball init + quarantined monkeypatches.

Holds the sentinel references for every pybaseball function the bot uses,
plus a single _init_pybaseball() entry point that:
  - rebinds pd.read_csv / pd.read_json to PyArrow-backed fast paths
  - fixes pybaseball 2.2.7's process_schedule under pandas 2.x CoW
  - swaps requests.Session.request to inject a real-browser User-Agent
    (some pybaseball endpoints 403 the default Python/Requests UA)

statcast_plots.py and statcast_stats.py read pybaseball functions via
attribute access on this module (e.g. ``statcast_patch.statcast_batter``)
so tests can patch them at their source.
"""

from __future__ import annotations

import os
from functools import wraps
from io import BytesIO, StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import matplotlib.pyplot as plt_mod  # noqa: F401
    from matplotlib.figure import Figure as Figure_cls  # noqa: F401

import pandas as pd

# --- Pybaseball Memory Optimization ---
# pybaseball wraps HTTP bodies in io.StringIO and hands them to pd.read_csv
# with no kwargs; pyarrow accepts StringIO but spends an extra ~12 MiB per
# parse on text→bytes re-buffering. Transparently rewrap as BytesIO so
# pyarrow sees bytes up front — measured savings on a Judge-2024-size CSV
# (2.1 MiB, 3337 rows x 118 cols): +17 MiB peak -> +5 MiB. Critical for
# staying under the Fly.io 512 MiB ceiling during /hotzones / /zone /
# /spray fetches.
#
# The patch is APPLIED inside _init_pybaseball() (first command call), not
# at module import — importing this module for type hints / tests must not
# silently replace pandas globals.
_original_read_csv = pd.read_csv
_original_read_json = pd.read_json


def fast_read_csv(*args, **kwargs):
    raw_bytes: bytes | None = None
    if args and isinstance(args[0], StringIO):
        raw_bytes = args[0].getvalue().encode("utf-8")

    def _call(engine: str | None, dtype_backend: str | None) -> pd.DataFrame:
        local_args = args if raw_bytes is None else (BytesIO(raw_bytes), *args[1:])
        local_kwargs = dict(kwargs)
        if engine is not None:
            local_kwargs["engine"] = engine
        else:
            local_kwargs.pop("engine", None)
        if dtype_backend is not None:
            local_kwargs["dtype_backend"] = dtype_backend
        else:
            local_kwargs.pop("dtype_backend", None)
        return _original_read_csv(*local_args, **local_kwargs)

    # Try fastest path first (pyarrow engine + arrow-backed dtypes), fall back
    # progressively if any caller feeds kwargs incompatible with pyarrow.
    last_exc: Exception | None = None
    for engine, backend in (("pyarrow", "pyarrow"), ("pyarrow", None), (None, None)):
        try:
            return _call(engine, backend)
        except Exception as exc:
            last_exc = exc
    # All three attempts failed; surface the final error.
    raise last_exc or RuntimeError("fast_read_csv: no attempt succeeded")


def fast_read_json(*args, **kwargs):
    kwargs["engine"] = "pyarrow"
    try:
        return _original_read_json(*args, **kwargs)
    except Exception:
        kwargs.pop("engine", None)
        return _original_read_json(*args, **kwargs)


def _patch_schedule_make_numeric() -> None:
    """
    Fix pybaseball 2.2.7's /schedule path under pandas 2.x Copy-on-Write.

    process_schedule does `df['Attendance'].replace('Unknown', NaN, inplace=True)`
    — a chained-assign inplace call that silently no-ops under CoW, leaving
    raw 'Unknown' strings in the column. make_numeric then does .astype(float)
    and raises ValueError. Replace make_numeric with a version that assigns
    the cleaned Series back explicitly so the conversion sees NaNs.
    """
    import numpy as np
    import pybaseball.team_results as tr

    def _cow_safe_make_numeric(data: pd.DataFrame) -> pd.DataFrame:
        if data["Attendance"].count() > 0:
            data["Attendance"] = data["Attendance"].str.replace(",", "")
            data["Attendance"] = data["Attendance"].replace(r"^Unknown$", np.nan, regex=True)
        else:
            data["Attendance"] = np.nan
        num_cols = ["R", "RA", "Inn", "Rank", "Attendance"]
        data[num_cols] = data[num_cols].astype(float)
        return data

    tr.make_numeric = cast("Any", _cow_safe_make_numeric)


# --- Lazy Loading Sentinels ---
# Populated by _init_pybaseball() on first use.
# Tests can mock these by assigning before _init_pybaseball() runs, or by
# patching via patch("statcast_patch.X", ...).
playerid_lookup: Any = None
plotting: Any = None
schedule_and_record: Any = None
statcast_batter: Any = None
statcast_batter_exitvelo_barrels: Any = None
statcast_batter_percentile_ranks: Any = None
statcast_pitcher: Any = None
statcast_pitcher_percentile_ranks: Any = None
statcast_pitcher_pitch_arsenal: Any = None
standings: Any = None

_pybaseball_initialized = False

# Matplotlib sentinels
plt: Any = None
Figure: Any = None


def _init_pybaseball() -> None:
    """Lazy initialization of pybaseball to save startup memory."""
    global playerid_lookup, plotting, schedule_and_record
    global statcast_batter, statcast_batter_exitvelo_barrels, statcast_batter_percentile_ranks
    global statcast_pitcher, statcast_pitcher_percentile_ranks, statcast_pitcher_pitch_arsenal
    global standings, plt, Figure, _pybaseball_initialized

    if _pybaseball_initialized:
        return

    # Quarantined pandas patches: applied here, not at module import, so
    # importing this module for type hints / unrelated tests doesn't silently
    # rebind pd.read_csv / pd.read_json. See fast_read_csv docstring above.
    pd.read_csv = cast("Any", fast_read_csv)
    pd.read_json = cast("Any", fast_read_json)

    import pybaseball
    import pybaseball.cache

    _cache_dir_str = os.environ.get("PYBASEBALL_CACHE")
    if _cache_dir_str:
        cache_path = Path(_cache_dir_str)
    else:
        cache_path = Path(__file__).parent.resolve() / ".pybaseball_cache"

    if not cache_path.exists():
        cache_path.mkdir(parents=True, exist_ok=True)

    pybaseball.cache.config.cache_directory = str(cache_path)
    pybaseball.cache.enable()

    # Some pybaseball endpoints (Baseball Reference, etc.) 403 on the default
    # Python/Requests User-Agent. Monkeypatch requests.Session to always send a
    # real browser UA. FanGraphs itself is no longer hit via pybaseball — see
    # fetch_fg_leaderboard() which uses curl_cffi to pass Cloudflare.
    import requests

    _orig_request = requests.Session.request

    @wraps(_orig_request)
    def _mock_request(self, method, url, **kwargs):
        kwargs.setdefault("headers", {})
        kwargs["headers"]["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        return _orig_request(self, method, url, **kwargs)

    requests.Session.request = cast("Any", _mock_request)

    _patch_schedule_make_numeric()

    # Export names to globals ONLY if they are not already set (e.g. by a mock)
    if playerid_lookup is None:
        playerid_lookup = pybaseball.playerid_lookup
    if plotting is None:
        plotting = pybaseball.plotting
    if schedule_and_record is None:
        schedule_and_record = pybaseball.schedule_and_record
    if statcast_batter is None:
        statcast_batter = pybaseball.statcast_batter
    if statcast_batter_exitvelo_barrels is None:
        statcast_batter_exitvelo_barrels = pybaseball.statcast_batter_exitvelo_barrels
    if statcast_batter_percentile_ranks is None:
        statcast_batter_percentile_ranks = pybaseball.statcast_batter_percentile_ranks
    if statcast_pitcher is None:
        statcast_pitcher = pybaseball.statcast_pitcher
    if statcast_pitcher_percentile_ranks is None:
        statcast_pitcher_percentile_ranks = pybaseball.statcast_pitcher_percentile_ranks
    if statcast_pitcher_pitch_arsenal is None:
        statcast_pitcher_pitch_arsenal = pybaseball.statcast_pitcher_pitch_arsenal
    if standings is None:
        standings = pybaseball.standings

    # Initialize Matplotlib
    import matplotlib.pyplot as plt_mod
    from matplotlib.figure import Figure as Figure_cls

    if plt is None:
        plt = plt_mod
    if Figure is None:
        Figure = Figure_cls

    _pybaseball_initialized = True


__all__ = [
    "Figure",
    "_init_pybaseball",
    "_patch_schedule_make_numeric",
    "fast_read_csv",
    "fast_read_json",
    "playerid_lookup",
    "plotting",
    "plt",
    "schedule_and_record",
    "standings",
    "statcast_batter",
    "statcast_batter_exitvelo_barrels",
    "statcast_batter_percentile_ranks",
    "statcast_pitcher",
    "statcast_pitcher_percentile_ranks",
    "statcast_pitcher_pitch_arsenal",
]
