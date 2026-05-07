"""
abs.py — Automated Ball-Strike challenge data from Baseball Savant.

The 2026 ABS challenge system gives each team two challenges per game.
Batter, pitcher, or catcher can request a Hawk-Eye review of the umpire's
ball/strike call. If the call is overturned the team retains the challenge;
if confirmed they lose it.

Source: https://baseballsavant.mlb.com/leaderboard/abs-challenges
The CSV download backing the leaderboard is publicly accessible — pass
`csv=true` and `challengeType=<role>` to get the raw rows.

Synchronous; call via asyncio.to_thread() from async Discord handlers.
No Discord imports.
"""

from __future__ import annotations

import csv
import io
import logging
import threading
import time

import requests

log = logging.getLogger("harry")

_BASE_URL = "https://baseballsavant.mlb.com/leaderboard/abs-challenges"
_REQUEST_TIMEOUT = 15

# Roles supported by the leaderboard's challengeType param.
ROLE_BATTER = "batter"
ROLE_PITCHER = "pitcher"
ROLE_CATCHER = "catcher"
ROLE_TEAM_SUMMARY = "team-summary"
PLAYER_ROLES: tuple[str, ...] = (ROLE_BATTER, ROLE_PITCHER, ROLE_CATCHER)

# Map common user-typed abbrevs to the abbrev Savant uses on its CSV.
# Most line up; these are the ones that don't.
_TEAM_TO_SAVANT: dict[str, str] = {
    "ARI": "AZ",
    "OAK": "ATH",
    "KCR": "KC",
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "CHW": "CWS",
    "WSN": "WSH",
    "WAS": "WSH",
}

# 1-hour cache. Savant updates the leaderboard daily, so an hour is still
# conservative and avoids refetching across a session of /abs commands.
_CACHE_TTL_SECONDS = 3600
_cache: dict[tuple[int, str], tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def normalize_team(abbr: str) -> str:
    """Normalize a user-typed team abbreviation to the form Savant uses."""
    up = abbr.strip().upper()
    return _TEAM_TO_SAVANT.get(up, up)


def _fetch_csv(year: int, challenge_type: str) -> list[dict]:
    """Fetch the ABS leaderboard CSV for one (year, role) combo.

    Cached for _CACHE_TTL_SECONDS. Numeric fields are parsed to float;
    blank cells become None so callers can distinguish 0 from missing.
    """
    key = (year, challenge_type)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

    params = {
        "year": year,
        "challengeType": challenge_type,
        "gameType": "regular",
        "level": "mlb",
        "csv": "true",
    }
    resp = requests.get(_BASE_URL, params=params, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()

    # Savant prepends a UTF-8 BOM to the CSV.
    text = resp.text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for raw in reader:
        row: dict = {}
        for k, v in raw.items():
            if v == "" or v is None:
                row[k] = None
                continue
            # Try numeric; fall back to the original string (for entity_name etc.)
            try:
                row[k] = float(v)
            except ValueError:
                row[k] = v
        rows.append(row)

    with _cache_lock:
        _cache[key] = (now, rows)
    return rows


def fetch_team_summary(team: str, year: int) -> dict:
    """Return the offense+defense ABS summary row for one team.

    Raises ValueError if the team isn't in the league feed.
    """
    sav = normalize_team(team)
    rows = _fetch_csv(year, ROLE_TEAM_SUMMARY)
    for r in rows:
        if r.get("team_abbr") == sav:
            return r
    raise ValueError(f"No ABS data for {team!r} in {year}.")


def fetch_team_top_challengers(team: str, year: int, limit: int = 3) -> list[dict]:
    """Return the team's top N individual challengers by raw challenge count.

    Pulls all three role feeds, filters to the team, dedupes by name (so a
    two-way player who challenged from both sides only appears once), and
    sorts by total challenges across roles. Each entry includes the role
    label so the embed can render "Aaron Judge (batter)".
    """
    sav = normalize_team(team)
    by_name: dict[str, dict] = {}
    for role in PLAYER_ROLES:
        for r in _fetch_csv(year, role):
            if r.get("team_abbr") != sav:
                continue
            name = r.get("entity_name")
            if not isinstance(name, str):
                continue
            existing = by_name.get(name)
            if existing is None or (r.get("n_challenges") or 0) > (
                existing.get("n_challenges") or 0
            ):
                by_name[name] = {**r, "role": role}

    ranked = sorted(
        by_name.values(),
        key=lambda r: r.get("n_challenges") or 0,
        reverse=True,
    )
    return ranked[:limit]


def fetch_player(first: str, last: str, year: int) -> dict:
    """Return ABS challenge stats for a single player.

    Searches all three role feeds (batter/pitcher/catcher) and merges any
    rows that match. Returns the per-role rows plus a `roles` list and a
    summed `totals` dict for the embed header.

    Raises ValueError if the player isn't in any feed.
    """
    target = f"{first.strip()} {last.strip()}".lower()
    matches: list[dict] = []
    for role in PLAYER_ROLES:
        for r in _fetch_csv(year, role):
            name = r.get("entity_name")
            if isinstance(name, str) and name.lower() == target:
                matches.append({**r, "role": role})

    if not matches:
        raise ValueError(f"No ABS challenge data for {first} {last} in {year}.")

    totals = {
        "n_challenges": sum((m.get("n_challenges") or 0) for m in matches),
        "n_overturns": sum((m.get("n_overturns") or 0) for m in matches),
        "n_confirms": sum((m.get("n_confirms") or 0) for m in matches),
        "n_strikeouts_flip": sum((m.get("n_strikeouts_flip") or 0) for m in matches),
        "n_walks_flip": sum((m.get("n_walks_flip") or 0) for m in matches),
    }
    name = matches[0].get("entity_name") or f"{first} {last}"
    team = matches[0].get("team_abbr") or ""

    return {
        "name": name,
        "team_abbr": team,
        "totals": totals,
        "roles": matches,
    }


def fetch_league_leaders(year: int, limit: int = 10, min_challenges: int = 3) -> list[dict]:
    """Top players league-wide by overturn rate (with a min-challenge floor).

    Combines the batter, pitcher, and catcher feeds. Players with fewer
    than `min_challenges` are filtered out — without that floor a player
    with one challenge and one overturn shows up at 100%, which isn't
    interesting. Ties on rate break by raw challenge count.
    """
    pool: list[dict] = []
    for role in PLAYER_ROLES:
        for r in _fetch_csv(year, role):
            n = r.get("n_challenges") or 0
            if n < min_challenges:
                continue
            pool.append({**r, "role": role})

    pool.sort(
        key=lambda r: (r.get("rate_overturns") or 0, r.get("n_challenges") or 0),
        reverse=True,
    )
    return pool[:limit]
