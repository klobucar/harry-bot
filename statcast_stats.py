"""
statcast_stats.py — Pure-data Statcast helpers (no plotting).

Player lookups, head-to-head matchup stats, pitch arsenal, hot/cold rolling
splits, exit-velocity, percentile ranks, standings, and schedule.

This is a thin **async facade** over `bigleague`: bigleague is async-native
and polars-backed, so these functions are now `async def` and are awaited
directly from the command handlers (no more `asyncio.to_thread`). The public
names, signatures, and return shapes are unchanged so the command layer is
unaffected.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import bigleague
from bigleague.http import mlb_get
from bigleague.mlb import TEAM_IDS
from bigleague.stats import (
    AB_EVENTS,
    HIT_EVENTS,
    hot_cold_batter,
    hot_cold_pitcher,
    matchup_stats,
    parse_exit_velo,
    parse_percentile_ranks,
    parse_pitch_arsenal,
    season_range,
)

__all__ = [
    "AB_EVENTS",
    "HIT_EVENTS",
    "compute_matchup_stats",
    "fetch_exit_velo",
    "fetch_hot_cold",
    "fetch_percentile_ranks",
    "fetch_pitch_arsenal",
    "fetch_player_mlb_years",
    "fetch_schedule",
    "fetch_standings",
    "resolve_player_id",
    "season_range",
]


# ---------------------------------------------------------------------------
# Player lookups
# ---------------------------------------------------------------------------


async def resolve_player_id(first: str, last: str) -> int | None:
    """Look up a player's MLBAM ID by name (case-insensitive, fuzzy).

    Returns the top match's MLBAM id, or None if nothing is found.
    """
    return await bigleague.resolve_id(first, last)


async def fetch_player_mlb_years(first: str, last: str) -> tuple[int, int]:
    """Return (debut_year, last_active_year) for a player.

    Falls back to (current_year - 3, current_year) if the data is missing;
    for active players whose register lags, the upper bound extends to the
    current year. Both handled inside bigleague.mlb_years.
    """
    return await bigleague.mlb_years(first, last)


# ---------------------------------------------------------------------------
# Head-to-head matchup stats
# ---------------------------------------------------------------------------


async def compute_matchup_stats(
    pitcher_id: int,
    batter_id: int,
    year: int,
) -> dict[str, int | float]:
    """Compute head-to-head stats for a batter against a pitcher.

    Returns a dict with keys: pa, ab, hits, strikeouts, batting_avg.
    Raises ValueError if no matchup data is found.
    """
    df = await bigleague.statcast_season(batter_id, year, "batter")
    if df.is_empty():
        raise ValueError(f"No Statcast data for batter_id={batter_id} in {year}.")
    try:
        return matchup_stats(df, pitcher_id)
    except ValueError as exc:
        raise ValueError(
            f"No plate appearances between pitcher {pitcher_id} and batter {batter_id} in {year}."
        ) from exc


# ---------------------------------------------------------------------------
# Pitch arsenal
# ---------------------------------------------------------------------------


async def fetch_pitch_arsenal(pitcher_id: int, year: int) -> list[dict]:
    """Fetch pitch arsenal stats for a pitcher in a given year.

    Returns a list of dicts with keys: pitch, mph, spin, usage (usage %),
    sorted by usage descending. Raises ValueError if the pitcher doesn't
    appear in arsenal data.
    """
    df = await bigleague.pitcher_pitch_arsenal(pitcher_id, year)
    arsenal = parse_pitch_arsenal(df)
    if not arsenal:
        raise ValueError(f"No arsenal data for pitcher_id={pitcher_id} in {year}.")
    # bigleague names the usage column `usage_pct`; the embed layer expects `usage`.
    return [
        {"pitch": p["pitch"], "mph": p["mph"], "spin": p["spin"], "usage": p["usage_pct"]}
        for p in arsenal
    ]


# ---------------------------------------------------------------------------
# Standings + schedule
# ---------------------------------------------------------------------------


async def fetch_standings(year: int) -> list[tuple[str, str]]:
    """Fetch MLB division standings for a season.

    Returns a list of (division_name, formatted_table) tuples, one per
    division. Raises ValueError if no data is returned.
    """
    divisions = await bigleague.standings(year)
    if not divisions:
        raise ValueError(f"No standings data available for {year}.")

    results: list[tuple[str, str]] = []
    for div in divisions:
        lines = []
        for t in div.get("teams", []):
            team = str(t.get("name", "???"))[:12]
            w = str(t.get("w", "?"))
            losses = str(t.get("l", "?"))
            gb = str(t.get("gb", "?"))
            lines.append(f"{team:<13} {w:>3}-{losses:<3} {gb:>5}")
        table = "```\n" + "\n".join(lines) + "\n```"
        results.append((str(div.get("division", "Division")), table))

    return results


# Reverse map: MLB Stats API team id -> 3-letter abbreviation, for rendering
# the opponent column in /schedule. Prefer the canonical 3-letter form when
# several aliases share an id.
_CANONICAL_ABBRS: frozenset[str] = frozenset(
    {"ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL", "DET",
     "HOU", "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
     "PHI", "PIT", "SD", "SF", "SEA", "STL", "TB", "TEX", "TOR", "WSN"}
)  # fmt: skip
_ID_TO_ABBR: dict[int, str] = {
    tid: abbr for abbr, tid in TEAM_IDS.items() if abbr in _CANONICAL_ABBRS
}


async def fetch_schedule(team: str, year: int) -> tuple[str, str]:
    """Fetch a team's schedule and record for a season.

    Returns (past_block, upcoming_block): formatted code-block strings for
    the last 5 completed games and next 5 scheduled games. Raises ValueError
    if no schedule data is found.
    """
    tid = TEAM_IDS.get(team.upper())
    if tid is None:
        raise ValueError(f"Unknown team abbreviation {team!r}.")

    data = await mlb_get(
        "/schedule",
        {
            "sportId": 1,
            "teamId": tid,
            "startDate": f"{year}-03-01",
            "endDate": f"{year}-11-30",
            "gameType": "R",
            "hydrate": "probablePitcher",
        },
    )

    games = [g for day in data.get("dates", []) for g in day.get("games", [])]
    if not games:
        raise ValueError(f"No schedule data for team={team!r} in {year}.")

    def _row(game: dict[str, Any], *, completed: bool) -> str:
        gd = str(game.get("gameDate", ""))
        day = gd[5:10].replace("-", "/") if len(gd) >= 10 else "?"
        teams = game.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        is_home = (home.get("team") or {}).get("id") == tid
        our, opp = (home, away) if is_home else (away, home)
        opp_team = opp.get("team") or {}
        opp_id = opp_team.get("id")
        opp_abbr = (_ID_TO_ABBR.get(opp_id) if isinstance(opp_id, int) else None) or str(
            opp_team.get("name", "???")
        )[:4]
        ha = "vs" if is_home else "@"
        if completed:
            won = bool(our.get("isWinner"))
            wl = "W" if won else "L"
            r = our.get("score", "?")
            ra = opp.get("score", "?")
            return f"{day:<7} {ha} {opp_abbr:<4}  {wl}  {r}-{ra}"
        t = gd[11:16] if len(gd) > 16 else "TBD"
        return f"{day:<7} {ha} {opp_abbr:<4}  {t}"

    def _state(game: dict[str, Any]) -> str:
        return (game.get("status") or {}).get("abstractGameState", "")

    completed = [g for g in games if _state(g) == "Final"]
    scheduled = [g for g in games if _state(g) in ("Preview", "Scheduled")]

    past_lines = [_row(g, completed=True) for g in completed[-5:]]
    next_lines = [_row(g, completed=False) for g in scheduled[:5]]

    past_block = "```\n" + "\n".join(past_lines) + "\n```" if past_lines else ""
    upcoming_block = (
        "```\n" + "\n".join(next_lines) + "\n```" if next_lines else "No upcoming games found."
    )
    return past_block, upcoming_block


# ---------------------------------------------------------------------------
# Hot / cold rolling splits
# ---------------------------------------------------------------------------


async def fetch_hot_cold(
    player_id: int,
    days: int,
    player_name: str,
    player_type: str = "batter",
) -> dict[str, str | int | float]:
    """Fetch rolling Statcast stats for a player over the last N days.

    player_type: "batter" or "pitcher". Returns a dict keyed for the embed.
    Raises ValueError if no data in the date range.
    """
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=days)

    if player_type == "pitcher":
        df = await bigleague.statcast_pitcher(player_id, start_dt, end_dt)
    else:
        df = await bigleague.statcast_batter(player_id, start_dt, end_dt)

    if df.is_empty():
        raise ValueError(f"No Statcast data for {player_name} in the last {days} days.")

    if player_type == "pitcher":
        r = hot_cold_pitcher(df)
        return {
            "period": f"Last {days} days",
            "Pitches": r["pitches"],
            "K": r["k"],
            "BB": r["bb"],
            "HR allowed": r["hr_allowed"],
            "PA faced": r["pa_faced"],
        }

    r = hot_cold_batter(df)
    return {
        "period": f"Last {days} days",
        "PA": r["pa"],
        "H": r["h"],
        "AB": r["ab"],
        "AVG": r["avg"],
        "OBP": r["obp"],
        "SLG": r["slg"],
        "OPS": r["ops"],
    }


# ---------------------------------------------------------------------------
# Exit velocity / barrels
# ---------------------------------------------------------------------------


async def fetch_exit_velo(player_id: int, year: int, player_name: str) -> dict[str, str]:
    """Fetch Statcast exit velocity and barrel stats for a batter in a year.

    Raises ValueError if the player doesn't appear in the exit-velo leaderboard.
    """
    df = await bigleague.batter_exit_velo(year, min_bbe=25)
    try:
        return parse_exit_velo(df, player_id)
    except ValueError as exc:
        raise ValueError(
            f"No exit velocity data for {player_name} in {year} (min 25 BBE required)."
        ) from exc


# ---------------------------------------------------------------------------
# Statcast percentile ranks
# ---------------------------------------------------------------------------


async def fetch_percentile_ranks(
    player_id: int,
    year: int,
    player_name: str,
    player_type: str = "pitcher",
) -> dict[str, str]:
    """Fetch Statcast percentile ranks for a player.

    player_type: "pitcher" or "batter". Returns dict of stat label →
    "NN th percentile". Raises ValueError if player not found.
    """
    if player_type == "pitcher":
        df = await bigleague.pitcher_percentile_ranks(player_id, year)
    else:
        df = await bigleague.batter_percentile_ranks(player_id, year)
    try:
        return parse_percentile_ranks(df, player_id, player_type)  # ty: ignore[invalid-argument-type]
    except ValueError as exc:
        raise ValueError(f"No percentile data found for {player_name} in {year}.") from exc
