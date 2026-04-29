"""
statcast_plots.py — Blocking pybaseball plot helpers.

Strike-zone, hot-zone, spray-chart, stadium, and matchup-zone PNG renderers.
All functions are synchronous (call via asyncio.to_thread() from async
command handlers). No Discord imports — pure data → PNG.

Reads pybaseball + matplotlib references via attribute access on
statcast_patch so test mocks (patch("statcast_patch.statcast_batter", ...))
take effect.
"""

from __future__ import annotations

import gc
import importlib.resources
import logging
from io import BytesIO

import pandas as pd

import statcast_patch

log = logging.getLogger("harry")


# ---------------------------------------------------------------------------
# Shared plot helper
# ---------------------------------------------------------------------------


def plot_to_buffer(data: pd.DataFrame, title: str, colorby: str = "pitch_type") -> BytesIO:
    """
    Plot a strike zone from a Statcast DataFrame and return the PNG as BytesIO.

    Uses pybaseball's built-in plot_strike_zone() — no manual matplotlib drawing.
    Closes the figure after saving to prevent memory leaks.

    Drops rows with NaN in the colorby column before plotting; pybaseball's
    pitch_code_to_name_map lookup raises KeyError on NaN values.

    Raises:
        ValueError: if data is empty or has no plottable rows after filtering.
    """
    if data is None or data.empty:
        raise ValueError("Cannot plot an empty dataset.")

    statcast_patch._init_pybaseball()

    # Guard against NaN in the column we're colouring by (most commonly pitch_type).
    # pybaseball's plot_strike_zone does a dict lookup on each value and crashes on NaN.
    if colorby in data.columns:
        data = data.dropna(subset=[colorby])

    if data.empty:
        raise ValueError(f"No plottable pitches after dropping rows with missing '{colorby}'.")

    ax = statcast_patch.plotting.plot_strike_zone(data, title=title, colorby=colorby, annotation="")
    fig = ax.get_figure()
    if not isinstance(fig, statcast_patch.Figure):
        raise RuntimeError(f"Expected Figure, got {type(fig)}")
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        buf.seek(0)
    finally:
        statcast_patch.plt.close(fig)  # Prevent memory leak regardless of savefig outcome
        # Aggressively clear matplotlib references
        del ax
        del fig
        del data
        # Figure↔Axes is a reference cycle: plt.close frees matplotlib's
        # C-side bitmap, but the Python objects only release on a cyclic
        # GC pass. Without this, RSS climbs ~10 MiB per chart on a long-
        # lived bot until gen-2 runs.
        gc.collect()

    return buf


# ---------------------------------------------------------------------------
# Per-command fetch + plot helpers
# ---------------------------------------------------------------------------


def _season_range(year: int) -> tuple[str, str]:
    return f"{year}-03-01", f"{year}-11-30"


def fetch_pitcher_zone(player_id: int, year: int, player_name: str) -> BytesIO:
    """
    Fetch a full season of Statcast pitcher data and return a strike-zone PNG.

    Raises ValueError if no data exists for the player/year.
    """
    statcast_patch._init_pybaseball()
    start_dt, end_dt = _season_range(year)
    raw: pd.DataFrame = statcast_patch.statcast_pitcher(start_dt, end_dt, player_id=player_id)

    if raw is None or raw.empty:
        raise ValueError(f"No Statcast pitcher data for player_id={player_id} in {year}.")

    # Memory optimization: plot_strike_zone only needs plate_x, plate_z, pitch_type
    data = raw[["plate_x", "plate_z", "pitch_type"]].copy()
    del raw

    return plot_to_buffer(data, title=f"{player_name} — {year} Strike Zone")


def fetch_batter_zone(player_id: int, year: int, player_name: str) -> BytesIO:
    """
    Fetch a full season of Statcast batter data and return a strike-zone PNG
    showing all pitches thrown to this batter.

    Raises ValueError if no data exists for the player/year.
    """
    statcast_patch._init_pybaseball()
    start_dt, end_dt = _season_range(year)
    raw: pd.DataFrame = statcast_patch.statcast_batter(start_dt, end_dt, player_id)

    if raw is None or raw.empty:
        raise ValueError(f"No Statcast batter data for player_id={player_id} in {year}.")

    # Memory optimization: plot_strike_zone only needs plate_x, plate_z, pitch_type
    data = raw[["plate_x", "plate_z", "pitch_type"]].copy()
    del raw

    return plot_to_buffer(data, title=f"{player_name} — {year} Pitches Received")


def fetch_hitter_hotzones(player_id: int, year: int, player_name: str) -> BytesIO:
    """
    Fetch a full season of Statcast batter data and return a stylized
    3x3 "hot zone" thermal grid showing Batting Average (BA) by zone.

    Zones 1-9 are the primary strike zone:
    1 2 3
    4 5 6
    7 8 9
    (from catcher's perspective)

    Returns a BytesIO buffer of the PNG plot.
    Raises ValueError if no data is found.
    """
    statcast_patch._init_pybaseball()
    start_dt, end_dt = _season_range(year)
    raw: pd.DataFrame = statcast_patch.statcast_batter(start_dt, end_dt, player_id)

    if raw is None or raw.empty:
        raise ValueError(f"No Statcast batter data for {player_name} in {year}.")

    # Memory optimization: hotzones only needs zone + events columns.
    # Drop the other ~90 columns immediately to free ~95% of memory.
    data = raw[["zone", "events"]].copy()
    del raw

    data = data.dropna(subset=["zone"])
    data = data[data["zone"].between(1, 9)]

    if data.empty:
        raise ValueError(
            f"No pitches recorded in the strike zone (1-9) for {player_name} in {year}."
        )

    hits = {"single", "double", "triple", "home_run"}
    ab_events = {
        "single",
        "double",
        "triple",
        "home_run",
        "field_out",
        "strikeout",
        "force_out",
        "grounded_into_double_play",
        "fielders_choice",
        "fielders_choice_out",
        "double_play",
        "triple_play",
    }

    def _get_ba(df):
        abs_count = df[df["events"].isin(ab_events)].shape[0]
        if abs_count == 0:
            return 0.0
        hits_count = df[df["events"].isin(hits)].shape[0]
        return hits_count / abs_count

    zone_ba = {}
    for z in range(1, 10):
        zone_df = data[data["zone"] == z]
        zone_ba[z] = _get_ba(zone_df)

    # Statcast zones 1-9 map perfectly to a 3x3 numpy array
    import numpy as np

    grid = np.array(
        [
            [zone_ba[1], zone_ba[2], zone_ba[3]],
            [zone_ba[4], zone_ba[5], zone_ba[6]],
            [zone_ba[7], zone_ba[8], zone_ba[9]],
        ]
    )

    import matplotlib.colors as mcolors

    fig = statcast_patch.Figure(figsize=(6, 6), dpi=100)
    ax = fig.add_subplot(111)

    # RdYlBu_r: Red-Yellow-Blue reversed (red is high). Normalized around .250.
    norm = mcolors.TwoSlopeNorm(vmin=0.100, vcenter=0.250, vmax=0.400)

    im = ax.imshow(grid, cmap="RdYlBu_r", norm=norm, interpolation="nearest")

    for i in range(3):
        for j in range(3):
            val = grid[i, j]
            color = "white" if val > 0.35 or val < 0.15 else "black"
            ax.text(
                j,
                i,
                f"{val:.3f}".replace("0.", "."),
                ha="center",
                va="center",
                color=color,
                fontsize=14,
                fontweight="bold",
            )

    ax.set_title(
        f"Hitter Hot Zones: {player_name} ({year})\n(Batting Average by Zone)",
        pad=20,
        fontsize=12,
        fontweight="bold",
    )

    ax.set_xticks([])
    ax.set_yticks([])

    for i in range(4):
        ax.axhline(i - 0.5, color="black", lw=2)
        ax.axvline(i - 0.5, color="black", lw=2)

    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.05)
    cbar.ax.set_ylabel("Batting Average", rotation=-90, va="bottom")

    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        buf.seek(0)
    finally:
        statcast_patch.plt.close(fig)
        del ax
        del fig
        del data
        gc.collect()

    return buf


def fetch_matchup_zone(
    pitcher_id: int,
    batter_id: int,
    year: int,
    pitcher_name: str,
    batter_name: str,
) -> BytesIO:
    """
    Fetch Statcast batter data and filter to pitches from a specific pitcher,
    then return a strike-zone PNG of that head-to-head matchup.

    Raises ValueError if the batter has no data, or if the two players never
    faced each other in the given season.
    """
    statcast_patch._init_pybaseball()
    start_dt, end_dt = _season_range(year)
    raw: pd.DataFrame = statcast_patch.statcast_batter(start_dt, end_dt, batter_id)

    if raw is None or raw.empty:
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")

    # Memory optimization: subset to needed columns before filtering
    data = raw[["pitcher", "plate_x", "plate_z", "pitch_type"]].copy()
    del raw

    matchup: pd.DataFrame = data[data["pitcher"] == pitcher_id].copy()
    del data

    if matchup.empty:
        raise ValueError(
            f"No pitches found from pitcher {pitcher_id} to batter {batter_id} in {year}."
        )

    return plot_to_buffer(matchup, title=f"{batter_name} vs. {pitcher_name} — {year}")


# ---------------------------------------------------------------------------
# Spray chart + stadium helpers
# ---------------------------------------------------------------------------

# True franchise renames — pybaseball's CSV still uses the old names.
_STADIUM_ALIASES: dict[str, str] = {
    "guardians": "indians",  # renamed 2022
}


def _load_known_stadiums() -> frozenset[str]:
    """Read unique team keys from pybaseball's bundled mlbstadiums.csv."""
    try:
        pkg = importlib.resources.files("pybaseball") / "data" / "mlbstadiums.csv"
        with importlib.resources.as_file(pkg) as p:
            df = pd.read_csv(p, usecols=["team"])
            return frozenset(df["team"].dropna().unique())
    except Exception:
        # Fallback: known-good set so normalization still works offline
        return frozenset(
            {
                "angels",
                "astros",
                "athletics",
                "blue_jays",
                "braves",
                "brewers",
                "cardinals",
                "cubs",
                "diamondbacks",
                "dodgers",
                "giants",
                "indians",
                "mariners",
                "marlins",
                "mets",
                "nationals",
                "orioles",
                "padres",
                "phillies",
                "pirates",
                "rangers",
                "rays",
                "red_sox",
                "reds",
                "rockies",
                "royals",
                "tigers",
                "twins",
                "white_sox",
                "yankees",
                "generic",
            }
        )


_KNOWN_STADIUMS: frozenset[str] | None = None


def _normalize_stadium(name: str) -> str:
    """
    Map a user-supplied team name to what pybaseball's spraychart expects.

    Steps:
      1. Lowercase + replace spaces/hyphens with underscores ("blue jays" → "blue_jays")
      2. Apply franchise rename aliases (guardians → indians)
      3. Fall back to "generic" if still not in the known set
    """
    global _KNOWN_STADIUMS
    if _KNOWN_STADIUMS is None:
        _KNOWN_STADIUMS = _load_known_stadiums()

    key = name.lower().replace(" ", "_").replace("-", "_")
    key = _STADIUM_ALIASES.get(key, key)
    return key if key in _KNOWN_STADIUMS else "generic"


# Maps pybaseball stadium key → MLB home_team code used in Statcast data.
# Used to filter batted balls to only those occurring AT the selected park.
_STADIUM_TO_TEAM_CODE: dict[str, str] = {
    "angels": "LAA",
    "astros": "HOU",
    "athletics": "OAK",
    "blue_jays": "TOR",
    "braves": "ATL",
    "brewers": "MIL",
    "cardinals": "STL",
    "cubs": "CHC",
    "diamondbacks": "ARI",
    "dodgers": "LAD",
    "giants": "SF",
    "indians": "CLE",  # Guardians still use CLE in Statcast
    "guardians": "CLE",
    "mariners": "SEA",
    "marlins": "MIA",
    "mets": "NYM",
    "nationals": "WSH",
    "orioles": "BAL",
    "padres": "SD",
    "phillies": "PHI",
    "pirates": "PIT",
    "rangers": "TEX",
    "rays": "TB",
    "red_sox": "BOS",
    "reds": "CIN",
    "rockies": "COL",
    "royals": "KC",
    "tigers": "DET",
    "twins": "MIN",
    "white_sox": "CWS",
    "yankees": "NYY",
}


def fetch_spray_chart(
    batter_id: int, year: int, batter_name: str, team_stadium: str = "generic"
) -> BytesIO:
    """
    Fetch Statcast batter data, filter to in-play events, and return a
    spray chart PNG overlaid on the given stadium.

    When team_stadium is not "generic", data is further filtered to only
    include batted balls from games played AT that stadium (home_team filter),
    so the chart reflects how the batter hits in that specific park.

    Raises ValueError if no batted-ball data found.
    """
    statcast_patch._init_pybaseball()
    start_dt, end_dt = _season_range(year)
    raw: pd.DataFrame = statcast_patch.statcast_batter(start_dt, end_dt, batter_id)

    if raw is None or raw.empty:
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")

    # Memory optimization: spraychart only needs a handful of columns
    keep_cols = ["type", "hc_x", "hc_y", "events", "home_team"]
    data = raw[[c for c in keep_cols if c in raw.columns]].copy()
    del raw

    # spraychart only makes sense for in-play events with coordinates
    in_play = data[data["type"] == "X"].dropna(subset=["hc_x", "hc_y"])
    del data

    if in_play.empty:
        raise ValueError(f"No batted-ball events with coordinates for {batter_name} in {year}.")

    stadium = _normalize_stadium(team_stadium)

    # Filter to games played AT the selected stadium, if one was specified
    team_code = _STADIUM_TO_TEAM_CODE.get(stadium)
    if team_code and "home_team" in in_play.columns:
        at_park = in_play[in_play["home_team"] == team_code]
        if at_park.empty:
            raise ValueError(
                f"No batted-ball data for {batter_name} at {team_stadium.title()} park in {year}. "
                f"They may not have played there."
            )
        in_play = at_park

    title = (
        f"{batter_name} — {year} @ {team_stadium.title()}"
        if team_code
        else f"{batter_name} — {year} Spray Chart"
    )
    ax = statcast_patch.plotting.spraychart(in_play, stadium, title=title)
    fig = ax.get_figure()
    if not isinstance(fig, statcast_patch.Figure):
        raise RuntimeError(f"Expected Figure, got {type(fig)}")
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        buf.seek(0)
    finally:
        statcast_patch.plt.close(fig)
        # Force garbage collection of the heavy dataframes and plot layers
        del ax
        del fig
        del in_play
        gc.collect()

    return buf


def fetch_stadium_info(team_alias: str) -> dict:
    """
    Fetch stadium name, location, and a visual outline for a given team.

    Returns:
        dict: {
            "name": str,
            "location": str,
            "image": BytesIO
        }
    """
    statcast_patch._init_pybaseball()

    stadium_key = _normalize_stadium(team_alias)
    if stadium_key == "generic" and team_alias.lower() != "generic":
        raise ValueError(f"Unknown team/stadium: {team_alias!r}")

    # 1. Fetch metadata from mlbstadiums.csv
    name = "Unknown Stadium"
    location = "Unknown Location"
    try:
        pkg = importlib.resources.files("pybaseball") / "data" / "mlbstadiums.csv"
        with importlib.resources.as_file(pkg) as p:
            df = pd.read_csv(p)
            row = df[df["team"] == stadium_key].iloc[0]
            name = str(row["name"])
            location = str(row["location"])
    except Exception:
        log.warning("Could not load stadium metadata for %s", stadium_key)

    # 2. Generate plot — pybaseball.plotting.plot_stadium returns an Axes
    ax = statcast_patch.plotting.plot_stadium(stadium_key)
    fig = ax.get_figure()
    if not isinstance(fig, statcast_patch.Figure):
        raise RuntimeError(f"Expected Figure, got {type(fig)}")

    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
        buf.seek(0)
    finally:
        statcast_patch.plt.close(fig)
        del ax
        del fig
        gc.collect()

    return {
        "name": name,
        "location": location,
        "image": buf,
    }
