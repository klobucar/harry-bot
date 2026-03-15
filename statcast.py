"""
statcast.py — Blocking pybaseball helpers.

All functions here are synchronous (no asyncio). They are designed to be
called via asyncio.to_thread() from the async command handlers.

No Discord imports — pure data / plot logic, making this independently testable.
"""

from __future__ import annotations

import gc
import importlib.resources
import logging
import urllib.request
from datetime import date, timedelta
from functools import wraps
from io import BytesIO

import matplotlib.pyplot as plt
import pandas as pd
import pybaseball
import requests
from matplotlib.figure import Figure
from pybaseball import (
    fg_batting_data,
    fg_pitching_data,
    playerid_lookup,
    plotting,
    schedule_and_record,
    statcast_batter,
    statcast_batter_exitvelo_barrels,
    statcast_batter_percentile_ranks,
    statcast_pitcher,
    statcast_pitcher_percentile_ranks,
    statcast_pitcher_pitch_arsenal,
)
from pybaseball import (
    standings as pb_standings,
)

from utils import current_year

# ---------------------------------------------------------------------------
# Setup & Configuration
# ---------------------------------------------------------------------------

# Enable pybaseball's internal cache to avoid API rate limits (e.g. FanGraphs)
# and dramatically speed up repeated lookups for the same player/season.
pybaseball.cache.enable()

# FanGraphs actively blocks default Python/Requests User-Agents with a 403 Forbidden.
# We monkeypatch the requests.Session to always send a real browser User-Agent globally.
_orig_request = requests.Session.request

@wraps(_orig_request)
def _mock_request(self, method, url, **kwargs):
    kwargs.setdefault("headers", {})
    kwargs["headers"]["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    return _orig_request(self, method, url, **kwargs)

requests.Session.request = _mock_request

log = logging.getLogger("harry")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Official at-bat event strings from Statcast. Module-level so they are not
#: re-created on every call to compute_matchup_stats().
AB_EVENTS: frozenset[str] = frozenset(
    {
        "single",
        "double",
        "triple",
        "home_run",
        "field_out",
        "strikeout",
        "strikeout_double_play",
        "double_play",
        "grounded_into_double_play",
        "field_error",
        "force_out",
        "fielders_choice",
        "fielders_choice_out",
        "other_out",
    }
)

HIT_EVENTS: frozenset[str] = frozenset({"single", "double", "triple", "home_run"})


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def season_range(year: int) -> tuple[str, str]:
    """Return (start_dt, end_dt) strings for a full MLB regular season."""
    return f"{year}-03-01", f"{year}-11-30"


def resolve_player_id(first: str, last: str) -> int | None:
    """
    Look up a player's MLBAM ID by name (case-insensitive).

    Uses fuzzy matching so minor typos (e.g. "Tarki" → "Tarik") still resolve.
    Returns the top match's key_mlbam integer, or None if nothing is found.
    """
    result: pd.DataFrame = playerid_lookup(last, first, fuzzy=True)
    if result.empty:
        return None
    mlbam_col = result["key_mlbam"].dropna()
    if mlbam_col.empty:
        return None
    return int(mlbam_col.iloc[0])


def fetch_player_mlb_years(first: str, last: str) -> tuple[int, int]:
    """
    Return (debut_year, last_active_year) for a player using playerid_lookup.

    mlb_played_first / mlb_played_last come from the Baseball Reference
    register embedded in pybaseball's lookup table.

    Falls back to (current_year - 3, current_year) if the data is missing.
    """
    cy = current_year()
    result: pd.DataFrame = playerid_lookup(last, first, fuzzy=True)
    if result.empty:
        return (cy - 3, cy)
    row = result.iloc[0]

    debut = row.get("mlb_played_first")
    last_yr = row.get("mlb_played_last")

    debut = int(debut) if pd.notna(debut) else (cy - 3)
    last_yr = int(last_yr) if pd.notna(last_yr) else cy
    # For active players mlb_played_last may lag; extend to current year
    last_yr = max(last_yr, cy)
    return (debut, last_yr)


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

    # Guard against NaN in the column we're colouring by (most commonly pitch_type).
    # pybaseball's plot_strike_zone does a dict lookup on each value and crashes on NaN.
    if colorby in data.columns:
        data = data.dropna(subset=[colorby])

    if data.empty:
        raise ValueError(f"No plottable pitches after dropping rows with missing '{colorby}'.")

    ax = plotting.plot_strike_zone(data, title=title, colorby=colorby, annotation="")
    fig = ax.get_figure()
    assert isinstance(fig, Figure)  # narrowed from Figure|SubFigure; plot_strike_zone always returns a Figure
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        buf.seek(0)
    finally:
        plt.close(fig)  # Prevent memory leak regardless of savefig outcome
        # Aggressively clear matplotlib references
        del ax
        del fig
        del data
        gc.collect()

    return buf


# ---------------------------------------------------------------------------
# Per-command fetch + plot helpers
# ---------------------------------------------------------------------------


def fetch_pitcher_zone(player_id: int, year: int, player_name: str) -> BytesIO:
    """
    Fetch a full season of Statcast pitcher data and return a strike-zone PNG.

    Raises ValueError if no data exists for the player/year.
    """
    start_dt, end_dt = season_range(year)
    data: pd.DataFrame = statcast_pitcher(start_dt, end_dt, player_id=player_id)

    if data is None or data.empty:
        raise ValueError(f"No Statcast pitcher data for player_id={player_id} in {year}.")

    return plot_to_buffer(data, title=f"{player_name} — {year} Strike Zone")


def fetch_batter_zone(player_id: int, year: int, player_name: str) -> BytesIO:
    """
    Fetch a full season of Statcast batter data and return a strike-zone PNG
    showing all pitches thrown to this batter.

    Raises ValueError if no data exists for the player/year.
    """
    start_dt, end_dt = season_range(year)
    data: pd.DataFrame = statcast_batter(start_dt, end_dt, player_id)

    if data is None or data.empty:
        raise ValueError(f"No Statcast batter data for player_id={player_id} in {year}.")

    return plot_to_buffer(data, title=f"{player_name} — {year} Pitches Received")


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
    start_dt, end_dt = season_range(year)
    data: pd.DataFrame = statcast_batter(start_dt, end_dt, batter_id)

    if data is None or data.empty:
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")

    matchup: pd.DataFrame = data[data["pitcher"] == pitcher_id].copy()

    if matchup.empty:
        raise ValueError(
            f"No pitches found from pitcher {pitcher_id} to batter {batter_id} in {year}."
        )

    return plot_to_buffer(matchup, title=f"{batter_name} vs. {pitcher_name} — {year}")


def compute_matchup_stats(
    pitcher_id: int,
    batter_id: int,
    year: int,
) -> dict[str, int | float]:
    """
    Fetch Statcast batter data and compute head-to-head stats against a pitcher.

    Returns a dict with keys: pa, ab, hits, strikeouts, batting_avg.
    Raises ValueError if no matchup data is found.
    """
    start_dt, end_dt = season_range(year)
    data: pd.DataFrame = statcast_batter(start_dt, end_dt, batter_id)

    if data is None or data.empty:
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")

    matchup: pd.DataFrame = data[data["pitcher"] == pitcher_id]

    if matchup.empty:
        raise ValueError(
            f"No plate appearances between pitcher {pitcher_id} and batter {batter_id} in {year}."
        )

    atbats = matchup[matchup["events"].isin(AB_EVENTS)]
    hits = atbats[atbats["events"].isin(HIT_EVENTS)]
    strikeouts: int = int(
        (matchup["events"] == "strikeout").sum()
        + (matchup["events"] == "strikeout_double_play").sum()
    )
    ab_count = len(atbats)
    hit_count = len(hits)

    stats = {
        "pa": len(matchup),
        "ab": ab_count,
        "hits": hit_count,
        "strikeouts": strikeouts,
        "batting_avg": (hit_count / ab_count) if ab_count > 0 else 0.0,
    }

    # Free memory
    del data
    del matchup
    del atbats
    del hits
    gc.collect()

    return stats


# ---------------------------------------------------------------------------
# Spray chart helper
# ---------------------------------------------------------------------------

# True franchise renames — pybaseball's CSV still uses the old names.
_STADIUM_ALIASES: dict[str, str] = {
    "guardians": "indians",  # renamed 2022
}


def _load_known_stadiums() -> frozenset[str]:
    """Read unique team keys from pybaseball's bundled mlbstadiums.csv."""
    try:
        # pybaseball ships the CSV as package data
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


_KNOWN_STADIUMS: frozenset[str] = _load_known_stadiums()


def _normalize_stadium(name: str) -> str:
    """
    Map a user-supplied team name to what pybaseball's spraychart expects.

    Steps:
      1. Lowercase + replace spaces/hyphens with underscores ("blue jays" → "blue_jays")
      2. Apply franchise rename aliases (guardians → indians)
      3. Fall back to "generic" if still not in the known set
    """
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
    "guardians": "CLE",  # Indians still use CLE in Statcast
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
    start_dt, end_dt = season_range(year)
    data: pd.DataFrame = statcast_batter(start_dt, end_dt, batter_id)

    if data is None or data.empty:
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")

    # spraychart only makes sense for in-play events with coordinates
    in_play = data[data["type"] == "X"].dropna(subset=["hc_x", "hc_y"])

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
    ax = plotting.spraychart(in_play, stadium, title=title)
    fig = ax.get_figure()
    assert isinstance(fig, Figure)  # narrowed from Figure|SubFigure; spraychart always returns a Figure
    buf = BytesIO()
    try:
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
        buf.seek(0)
    finally:
        plt.close(fig)
        # Force garbage collection of the heavy dataframes and plot layers
        del ax
        del fig
        del in_play
        del data
        gc.collect()

    return buf


# ---------------------------------------------------------------------------
# Pitch arsenal helper
# ---------------------------------------------------------------------------


def fetch_pitch_arsenal(pitcher_id: int, year: int) -> list[dict]:
    """
    Fetch pitch arsenal stats for a specific pitcher in a given year.

    Returns a list of dicts with keys: pitch, mph, spin, usage.
    Raises ValueError if the pitcher doesn't appear in arsenal data.
    """
    # Fetch all pitchers with low minP so fringe guys aren't excluded
    speed_df: pd.DataFrame = statcast_pitcher_pitch_arsenal(
        year, minP=10, arsenal_type="avg_speed"
    )
    spin_df: pd.DataFrame = statcast_pitcher_pitch_arsenal(
        year, minP=10, arsenal_type="avg_spin"
    )
    usage_df: pd.DataFrame = statcast_pitcher_pitch_arsenal(year, minP=10, arsenal_type="n_")

    def _filter(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        return df[df["pitcher"] == pitcher_id]

    speed_row = _filter(speed_df)
    spin_row = _filter(spin_df)
    usage_row = _filter(usage_df)

    if speed_row.empty:
        raise ValueError(f"No arsenal data for pitcher_id={pitcher_id} in {year}.")

    # The columns in 'speed_row' are formatted like 'ff_avg_speed', 'sl_avg_speed', etc.
    # We find all pitches by looking for the '_avg_speed' suffix.
    prefixes = [c.replace("_avg_speed", "") for c in speed_row.columns if c.endswith("_avg_speed")]

    # First, calculate total pitches so we can compute true usage percentages
    total_pitches = 0
    for prefix in prefixes:
        usage_col = f"n_{prefix}"
        if usage_col in usage_row.columns:
            val = usage_row[usage_col].iloc[0]
            if pd.notna(val):
                total_pitches += float(val)

    results: list[dict] = []
    for prefix in prefixes:
        speed_col = f"{prefix}_avg_speed"
        spin_col = f"{prefix}_avg_spin"
        usage_col = f"n_{prefix}"

        mph_val = speed_row[speed_col].iloc[0] if speed_col in speed_row.columns else float("nan")
        spin_val = spin_row[spin_col].iloc[0] if spin_col in spin_row.columns else float("nan")
        usage_val = usage_row[usage_col].iloc[0] if usage_col in usage_row.columns else float("nan")

        if pd.isna(mph_val) or pd.isna(usage_val) or total_pitches == 0:
            continue

        pct = (float(usage_val) / total_pitches) * 100

        results.append(
            {
                "pitch": prefix.upper(),
                "mph": float(mph_val),
                "spin": float(spin_val) if not pd.isna(spin_val) else 0.0,
                "usage": pct,
            }
        )

    results.sort(key=lambda x: x["usage"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# FanGraphs stats helper (auto-detects pitcher vs batter)
# ---------------------------------------------------------------------------

_PITCHING_KEYS = ["W", "L", "ERA", "FIP", "xFIP", "WHIP", "K/9", "BB/9", "HR/9", "WAR", "IP"]
_BATTING_KEYS = ["AVG", "OBP", "SLG", "OPS", "wOBA", "wRC+", "HR", "RBI", "SB", "WAR", "PA"]


def _name_match(df: pd.DataFrame, first: str, last: str) -> pd.DataFrame:
    """Filter FanGraphs DataFrame by player name (case-insensitive)."""
    target = f"{first.lower()} {last.lower()}"
    return df[df["Name"].str.lower() == target]


def fetch_player_stats(first: str, last: str, year: int) -> dict:
    """
    Fetch FanGraphs season stats for a player, auto-detecting pitcher vs batter.

    Tries pitching first (qual=1 IP), then batting (qual=1 PA).
    Returns dict with keys: type, team, stats.
    Raises ValueError if player not found in either leaderboard.
    """
    # Try pitching first
    pitch_df = pitching_stats(year, qual=1)
    if pitch_df is not None and not pitch_df.empty:
        row = _name_match(pitch_df, first, last)
        if not row.empty:
            r = row.iloc[0]
            return {
                "type": "pitcher",
                "team": r.get("Team", "N/A"),
                "stats": {k: _fmt(r.get(k)) for k in _PITCHING_KEYS if k in r.index},
            }

    # Try batting
    bat_df = batting_stats(year, qual=1)
    if bat_df is not None and not bat_df.empty:
        row = _name_match(bat_df, first, last)
        if not row.empty:
            r = row.iloc[0]
            return {
                "type": "batter",
                "team": r.get("Team", "N/A"),
                "stats": {k: _fmt(r.get(k)) for k in _BATTING_KEYS if k in r.index},
            }

    raise ValueError(f"No FanGraphs stats found for {first} {last} in {year}.")


def fetch_player_stats_compare(first: str, last: str, year: int) -> dict:
    """Thin alias used by /compare — identical to fetch_player_stats."""
    return fetch_player_stats(first, last, year)


def fetch_career_stats(first: str, last: str) -> dict:
    """
    Auto-detect pitcher/batter and return FanGraphs stats for the current year.

    Simpler API than aggregate_career_frames: single network call per type,
    no year-by-year batching. Useful for tests and quick lookups.

    Raises ValueError if player not found in either pitching or batting data.
    """
    cy = current_year()

    try:
        pitch_df = fg_pitching_data(cy, qual=1)
    except ValueError as e:
        if "columns passed" in str(e):
            pitch_df = pd.DataFrame()
        else:
            raise
    if pitch_df is not None and not pitch_df.empty:
        row = _name_match(pitch_df, first, last)
        if not row.empty:
            r = row.iloc[0]
            return {
                "type": "pitcher",
                "team": r.get("Team", "N/A"),
                "stats": {k: _fmt(r.get(k)) for k in _PITCHING_KEYS if k in r.index},
            }

    try:
        bat_df = fg_batting_data(cy, qual=1)
    except ValueError as e:
        if "columns passed" in str(e):
            bat_df = pd.DataFrame()
        else:
            raise
    if bat_df is not None and not bat_df.empty:
        row = _name_match(bat_df, first, last)
        if not row.empty:
            r = row.iloc[0]
            return {
                "type": "batter",
                "team": r.get("Team", "N/A"),
                "stats": {k: _fmt(r.get(k)) for k in _BATTING_KEYS if k in r.index},
            }

    raise ValueError(f"No FanGraphs career data found for {first} {last}.")


def _fmt(val: object) -> str:
    """Format a stat value for display."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if isinstance(val, float):
        return f"{val:.3f}" if val < 10 else f"{val:.1f}"
    return str(val)


# ---------------------------------------------------------------------------
# Standings helper
# ---------------------------------------------------------------------------

_DIVISION_NAMES = [
    "AL East",
    "AL Central",
    "AL West",
    "NL East",
    "NL Central",
    "NL West",
]


def fetch_standings(year: int) -> list[tuple[str, str]]:
    """
    Fetch MLB division standings for a season.

    Returns a list of (division_name, formatted_table) tuples, one per division.
    Raises ValueError if no data is returned.
    """
    data = pb_standings(year)

    if not data:
        raise ValueError(f"No standings data available for {year}.")

    results: list[tuple[str, str]] = []
    for i, df in enumerate(data):
        div_name = _DIVISION_NAMES[i] if i < len(_DIVISION_NAMES) else f"Division {i + 1}"
        # Build a compact code-block table: Team | W | L | GB
        lines = []
        for _, row in df.iterrows():
            team = str(row.get("Tm", "???"))[:12]
            w = str(row.get("W", "?"))
            losses = str(row.get("L", "?"))
            gb = str(row.get("GB", "?"))
            lines.append(f"{team:<13} {w:>3}-{losses:<3} {gb:>5}")
        table = "```\n" + "\n".join(lines) + "\n```"
        results.append((div_name, table))

    return results


# ---------------------------------------------------------------------------
# Schedule helper
# ---------------------------------------------------------------------------


def fetch_schedule(team: str, year: int) -> tuple[str, str]:
    """
    Fetch a team's schedule and record for a season.

    Returns (past_block, upcoming_block): formatted code-block strings for
    the last 5 completed games and next 5 scheduled games.
    Raises ValueError if no schedule data found.
    """
    df: pd.DataFrame = schedule_and_record(year, team)

    if df is None or df.empty:
        raise ValueError(f"No schedule data for team={team!r} in {year}.")

    # Completed games have a W/L result
    completed = df[df["W/L"].notna() & (df["W/L"] != "")]
    scheduled = df[df["W/L"].isna() | (df["W/L"] == "")]

    def _fmt_row(row: pd.Series, is_result: bool) -> str:
        date = str(row.get("Date", ""))[:6]
        opp = str(row.get("Opp", "???"))[:4]
        ha = "vs" if row.get("H/A", "") != "@" else "@"
        if is_result:
            wl = str(row.get("W/L", ""))[:1]
            r = str(int(row["R"])) if pd.notna(row.get("R")) else "?"
            ra = str(int(row["RA"])) if pd.notna(row.get("RA")) else "?"
            return f"{date:<7} {ha} {opp:<4}  {wl}  {r}-{ra}"
        else:
            time = str(row.get("Time", ""))[:5]
            return f"{date:<7} {ha} {opp:<4}  {time}"

    past_lines = [_fmt_row(r, True) for _, r in completed.tail(5).iterrows()]
    next_lines = [_fmt_row(r, False) for _, r in scheduled.head(5).iterrows()]

    past_block = "```\n" + "\n".join(past_lines) + "\n```" if past_lines else ""
    upcoming_block = (
        "```\n" + "\n".join(next_lines) + "\n```" if next_lines else "No upcoming games found."
    )

    return past_block, upcoming_block


# ---------------------------------------------------------------------------
# Hot / cold rolling splits
# ---------------------------------------------------------------------------


def fetch_hot_cold(
    player_id: int,
    days: int,
    player_name: str,
    player_type: str = "batter",
) -> dict[str, str | int | float]:
    """
    Fetch rolling Statcast stats for a player over the last N days.

    player_type: "batter" or "pitcher"
    Returns dict with AVG, OBP, SLG, wOBA (batter) or ERA, K/9, WHIP proxy (pitcher).
    Raises ValueError if no data in the date range.
    """
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    if player_type == "pitcher":
        data: pd.DataFrame = statcast_pitcher(start_str, end_str, player_id=player_id)
    else:
        data = statcast_batter(start_str, end_str, player_id)

    if data is None or data.empty:
        raise ValueError(f"No Statcast data for {player_name} in the last {days} days.")

    if player_type == "pitcher":
        # Compute ERA proxy from runs allowed and innings pitched
        total_pitches = len(data)
        k = int(
            (data["events"] == "strikeout").sum()
            + (data["events"] == "strikeout_double_play").sum()
        )
        bb = int((data["events"] == "walk").sum())
        pa = data["events"].notna().sum()
        hr = int((data["events"] == "home_run").sum())
        return {
            "period": f"Last {days} days",
            "Pitches": total_pitches,
            "K": k,
            "BB": bb,
            "HR allowed": hr,
            "PA faced": int(pa),
        }
    else:
        ab_df = data[data["events"].isin(AB_EVENTS)]
        hit_df = ab_df[ab_df["events"].isin(HIT_EVENTS)]
        ab = len(ab_df)
        h = len(hit_df)
        bb = int((data["events"] == "walk").sum())
        pa = ab + bb
        avg = h / ab if ab > 0 else 0.0
        obp = (h + bb) / pa if pa > 0 else 0.0
        tb = (
            int((ab_df["events"] == "single").sum())
            + 2 * int((ab_df["events"] == "double").sum())
            + 3 * int((ab_df["events"] == "triple").sum())
            + 4 * int((ab_df["events"] == "home_run").sum())
        )
        slg = tb / ab if ab > 0 else 0.0
        
        stats = {
            "period": f"Last {days} days",
            "PA": pa,
            "H": h,
            "AB": ab,
            "AVG": round(avg, 3),
            "OBP": round(obp, 3),
            "SLG": round(slg, 3),
            "OPS": round(obp + slg, 3),
        }

        # Free memory
        del data
        del ab_df
        del hit_df
        gc.collect()

        return stats


# ---------------------------------------------------------------------------
# Exit velocity / barrels
# ---------------------------------------------------------------------------


def fetch_exit_velo(player_id: int, year: int, player_name: str) -> dict[str, str | float]:
    """
    Fetch Statcast exit velocity and barrel stats for a batter in a given year.

    Raises ValueError if the player doesn't appear in the exit velo leaderboard.
    """
    data: pd.DataFrame = statcast_batter_exitvelo_barrels(year, minBBE=25)

    if data is None or data.empty:
        raise ValueError(f"No exit velocity data available for {year}.")

    row = data[data["player_id"] == player_id]

    if row.empty:
        raise ValueError(
            f"No exit velocity data for {player_name} in {year} (min 25 BBE required)."
        )

    r = row.iloc[0]
    return {
        "Avg Exit Velo": f"{r.get('avg_hit_speed', float('nan')):.1f} mph",
        "Max Exit Velo": f"{r.get('max_hit_speed', float('nan')):.1f} mph",
        "Avg Launch Angle": f"{r.get('avg_hit_angle', float('nan')):.1f}°",
        "Barrel %": f"{r.get('brl_percent', float('nan')):.1f}%",
        "Hard Hit %": f"{r.get('anglesweetspotpercent', float('nan')):.1f}%",
        "Barrels": str(int(r.get("brl_pa", 0))),
        "BBE": str(int(r.get("pa", 0))),
    }


# ---------------------------------------------------------------------------
# Statcast percentile ranks
# ---------------------------------------------------------------------------

_PITCHER_PERCENTILE_COLS = {
    "hard_hit_percent": "Hard Hit%",
    "k_percent": "K%",
    "bb_percent": "BB%",
    "xwoba": "xwOBA",
    "xera": "xERA",
    "fastball_avg_speed": "FB Velo",
    "spin_rate_percent": "Spin Rate",
}

_BATTER_PERCENTILE_COLS = {
    "exit_velocity_avg": "Exit Velo",
    "hard_hit_percent": "Hard Hit%",
    "k_percent": "K%",
    "bb_percent": "BB%",
    "xwoba": "xwOBA",
    "xba": "xBA",
    "xslg": "xSLG",
    "sprint_speed": "Sprint Speed",
}


def fetch_percentile_ranks(
    player_id: int,
    year: int,
    player_name: str,
    player_type: str = "pitcher",
) -> dict[str, str]:
    """
    Fetch Statcast percentile ranks for a player.

    player_type: "pitcher" or "batter"
    Returns dict of stat_name → "NN%" (formatted percentile).
    Raises ValueError if player not found.
    """
    if player_type == "pitcher":
        data: pd.DataFrame = statcast_pitcher_percentile_ranks(year)
        cols = _PITCHER_PERCENTILE_COLS
    else:
        data = statcast_batter_percentile_ranks(year)
        cols = _BATTER_PERCENTILE_COLS

    if data is None or data.empty:
        raise ValueError(f"No percentile rank data for {year}.")

    # Try to find by numeric ID across possible column names
    row = pd.DataFrame()
    for col in ("player_id", "pitcher_id", "batter_id", "mlbam_id"):
        if col in data.columns:
            row = data[data[col] == player_id]
            if not row.empty:
                break

    if row.empty:
        raise ValueError(f"No percentile data found for {player_name} in {year}.")

    r = row.iloc[0]
    result: dict[str, str] = {}
    for raw_col, label in cols.items():
        if raw_col in r.index and pd.notna(r[raw_col]):
            result[label] = f"{int(r[raw_col])}th percentile"
    return result


# ---------------------------------------------------------------------------
# Career stats (FanGraphs aggregate)
# ---------------------------------------------------------------------------


def fetch_year_fangraphs(yr: int, player_type: str, first: str, last: str) -> pd.DataFrame | None:
    """
    Blocking helper: fetch one year of FanGraphs pitching or batting stats via JSON API.

    Returns DataFrame with a '_year' column, or None on any error.
    Designed to be called via asyncio.to_thread(); concurrency is managed
    by the caller (asyncio.gather + Semaphore).
    """
    try:
        fn = fg_pitching_data if player_type == "pitcher" else fg_batting_data
        log.info(f"FanGraphs: Requesting {player_type} stats for {yr}...")
        
        try:
            df = fn(yr, yr, qual=1)
        except ValueError as e:
            # FanGraphs returns a malformed 1-column response for future/empty years
            if "columns passed" in str(e):
                log.info(f"FanGraphs: No valid data for {yr} (likely future/empty season).")
                return None
            raise
            
        if df is not None and not df.empty:
            res = _name_match(df, first, last)
            
            # Immediately delete the full MLB dataframe chunk to clear RAM
            del df
            gc.collect()
            
            if not res.empty:
                log.info(f"FanGraphs: Found {first} {last} for {player_type} in {yr}.")
                res = res.copy()
                res["_year"] = yr
                return res
        else:
            if df is not None:
                del df
            gc.collect()
            
        log.warning(f"FanGraphs: Returned empty dataframe for {player_type} in {yr}.")
    except Exception as exc:
        log.error(f"FanGraphs Error [{player_type} {yr}]: {exc}", exc_info=True)
    return None


def aggregate_career_frames(
    pitch_frames: list[pd.DataFrame],
    bat_frames: list[pd.DataFrame],
    first: str,
    last: str,
    years: list[int],
) -> dict:
    """
    Pure aggregation (no I/O): combine per-year DataFrames into a career summary.

    Tries pitching first, then batting.
    Raises ValueError if the player isn't found in either set.
    """

    def _agg_pitcher(rows: pd.DataFrame) -> dict[str, str]:
        totals: dict[str, str] = {}
        for col in ("W", "L", "SV", "G", "GS"):
            if col in rows.columns:
                totals[col] = _fmt(rows[col].sum())
        if "IP" in rows.columns:
            totals["IP"] = _fmt(rows["IP"].sum())
        ip_w = rows.get("IP", pd.Series([1.0] * len(rows)))
        ip_sum = ip_w.sum()
        w = ip_w / ip_sum if ip_sum > 0 else pd.Series([1.0 / len(rows)] * len(rows))
        for col in ("ERA", "FIP", "WHIP", "K/9", "BB/9", "WAR"):
            if col in rows.columns:
                totals[col] = _fmt((rows[col] * w.values).sum())
        return totals

    def _agg_batter(rows: pd.DataFrame) -> dict[str, str]:
        totals: dict[str, str] = {}
        for col in ("G", "PA", "AB", "H", "HR", "RBI", "SB", "BB"):
            if col in rows.columns:
                totals[col] = _fmt(rows[col].sum())
        pa_w = rows.get("PA", pd.Series([1.0] * len(rows)))
        pa_sum = pa_w.sum()
        w = pa_w / pa_sum if pa_sum > 0 else pd.Series([1.0 / len(rows)] * len(rows))
        for col in ("AVG", "OBP", "SLG", "OPS", "wRC+", "WAR"):
            if col in rows.columns:
                totals[col] = _fmt((rows[col] * w.values).sum())
        return totals

    def _agg(frames: list[pd.DataFrame], player_type: str) -> dict | None:
        if not frames:
            return None
        combined = pd.concat(frames, ignore_index=True)
        rows = _name_match(combined, first, last)
        if rows.empty:
            return None

        seasons = rows["_year"].nunique()
        sub = _agg_pitcher(rows) if player_type == "pitcher" else _agg_batter(rows)
        totals = {"Seasons": str(seasons), **sub}
        span = f"{years[0]}-{years[-1]}"
        return {"type": player_type, "team": f"Career ({span})", "stats": totals}

    result = _agg(pitch_frames, "pitcher") or _agg(bat_frames, "batter")
    if result is None:
        raise ValueError(f"No FanGraphs data found for {first} {last} in {years[0]}-{years[-1]}.")
    return result


# ---------------------------------------------------------------------------
# Leaderboard (top-N by stat)
# ---------------------------------------------------------------------------


def fetch_leaderboard(stat: str, year: int, player_type: str = "auto") -> list[dict]:
    """
    Return the top 10 players for a given FanGraphs stat in a season.

    player_type: "pitcher", "batter", or "auto" (tries both and picks the one containing stat).
    Returns list of dicts: rank, name, team, value.
    Raises ValueError if stat not found in the leaderboard.
    """

    def _from_df(df: pd.DataFrame) -> list[dict]:
        if df is None or df.empty:
            return []
        # Case-insensitive column match
        col_map = {c.lower(): c for c in df.columns}
        col = col_map.get(stat.lower())
        if col is None:
            return []
        top = df.nlargest(10, col)[["Name", "Team", col]].reset_index(drop=True)
        return [
            {
                "rank": i + 1,
                "name": row["Name"],
                "team": row.get("Team", "—"),
                "value": _fmt(row[col]),
            }
            for i, row in top.iterrows()
        ]

    boards: list[list[dict]] = []

    if player_type in ("pitcher", "auto"):
        try:
            df = fg_pitching_data(year, qual=1)
            boards.append(_from_df(df))
        except ValueError as e:
            if "columns passed" not in str(e):
                raise

    if player_type in ("batter", "auto"):
        try:
            df = fg_batting_data(year, qual=1)
            boards.append(_from_df(df))
        except ValueError as e:
            if "columns passed" not in str(e):
                raise

    for board in boards:
        if board:
            return board

    raise ValueError(
        f"Stat '{stat}' not found in FanGraphs leaderboards for {year}. "
        "Try a column name like ERA, WAR, HR, K%, OPS, wRC+, FIP, WHIP."
    )
