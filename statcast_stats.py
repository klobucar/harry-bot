"""
statcast_stats.py — Pure-data Statcast helpers (no plotting).

Player lookups, head-to-head matchup stats, pitch arsenal, hot/cold rolling
splits, exit-velocity, percentile ranks, standings, and schedule.

All functions are synchronous (call via asyncio.to_thread() from async
command handlers). No Discord imports, no matplotlib.

Reads pybaseball references via attribute access on statcast_patch so test
mocks (patch("statcast_patch.statcast_batter", ...)) take effect.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import statcast_patch
from utils import current_year

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
    statcast_patch._init_pybaseball()
    result: pd.DataFrame = statcast_patch.playerid_lookup(last, first, fuzzy=True)
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
    statcast_patch._init_pybaseball()
    result: pd.DataFrame = statcast_patch.playerid_lookup(last, first, fuzzy=True)
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
# Head-to-head matchup stats
# ---------------------------------------------------------------------------


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
    statcast_patch._init_pybaseball()
    start_dt, end_dt = season_range(year)
    raw: pd.DataFrame = statcast_patch.statcast_batter(start_dt, end_dt, batter_id)

    if raw is None or raw.empty:
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")

    # Memory optimization: only need pitcher + events columns
    data = raw[["pitcher", "events"]].copy()
    del raw

    matchup: pd.DataFrame = data[data["pitcher"] == pitcher_id]
    del data

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

    del matchup
    del atbats
    del hits

    return stats


# ---------------------------------------------------------------------------
# Pitch arsenal
# ---------------------------------------------------------------------------


def fetch_pitch_arsenal(pitcher_id: int, year: int) -> list[dict]:
    """
    Fetch pitch arsenal stats for a specific pitcher in a given year.

    Returns a list of dicts with keys: pitch, mph, spin, usage.
    Raises ValueError if the pitcher doesn't appear in arsenal data.
    """
    statcast_patch._init_pybaseball()
    # Fetch all pitchers with low minP so fringe guys aren't excluded
    speed_df: pd.DataFrame = statcast_patch.statcast_pitcher_pitch_arsenal(
        year, minP=10, arsenal_type="avg_speed"
    )
    spin_df: pd.DataFrame = statcast_patch.statcast_pitcher_pitch_arsenal(
        year, minP=10, arsenal_type="avg_spin"
    )
    usage_df: pd.DataFrame = statcast_patch.statcast_pitcher_pitch_arsenal(
        year, minP=10, arsenal_type="n_"
    )

    def _filter(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        return df[df["pitcher"] == pitcher_id]

    speed_row = _filter(speed_df)
    spin_row = _filter(spin_df)
    usage_row = _filter(usage_df)

    if speed_row.empty:
        raise ValueError(f"No arsenal data for pitcher_id={pitcher_id} in {year}.")

    # Columns are formatted like 'ff_avg_speed', 'sl_avg_speed', etc.
    # Find pitch prefixes by looking for the '_avg_speed' suffix.
    prefixes = [c.replace("_avg_speed", "") for c in speed_row.columns if c.endswith("_avg_speed")]

    # Calculate total pitches first so we can compute true usage percentages
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
# Standings + schedule
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
    statcast_patch._init_pybaseball()
    data = statcast_patch.standings(year)

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


def fetch_schedule(team: str, year: int) -> tuple[str, str]:
    """
    Fetch a team's schedule and record for a season.

    Returns (past_block, upcoming_block): formatted code-block strings for
    the last 5 completed games and next 5 scheduled games.
    Raises ValueError if no schedule data found.
    """
    statcast_patch._init_pybaseball()
    df: pd.DataFrame = statcast_patch.schedule_and_record(year, team)

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

    statcast_patch._init_pybaseball()
    if player_type == "pitcher":
        raw: pd.DataFrame = statcast_patch.statcast_pitcher(start_str, end_str, player_id=player_id)
    else:
        raw = statcast_patch.statcast_batter(start_str, end_str, player_id)

    if raw is None or raw.empty:
        raise ValueError(f"No Statcast data for {player_name} in the last {days} days.")

    # Memory optimization: only need events column for stat calculations
    data = raw[["events"]].copy()
    del raw

    if data.empty:
        raise ValueError(f"No Statcast data for {player_name} in the last {days} days.")

    if player_type == "pitcher":
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

    del data
    del ab_df
    del hit_df

    return stats


# ---------------------------------------------------------------------------
# Exit velocity / barrels
# ---------------------------------------------------------------------------


def fetch_exit_velo(player_id: int, year: int, player_name: str) -> dict[str, str | float]:
    """
    Fetch Statcast exit velocity and barrel stats for a batter in a given year.

    Raises ValueError if the player doesn't appear in the exit velo leaderboard.
    """
    statcast_patch._init_pybaseball()
    data: pd.DataFrame = statcast_patch.statcast_batter_exitvelo_barrels(year, minBBE=25)

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
    statcast_patch._init_pybaseball()
    if player_type == "pitcher":
        data: pd.DataFrame = statcast_patch.statcast_pitcher_percentile_ranks(year)
        cols = _PITCHER_PERCENTILE_COLS
    else:
        data = statcast_patch.statcast_batter_percentile_ranks(year)
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
