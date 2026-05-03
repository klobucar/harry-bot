"""
mlb_api.py — Synchronous helpers for the official MLB Stats API.

All functions are blocking — call via asyncio.to_thread().
Uses requests (a pybaseball transitive dep) — no extra install needed.
All functions are blocking — call via asyncio.to_thread().
No Discord imports.

MLB Stats API: https://statsapi.mlb.com/api/v1/

httpx would only help if we were truly async here; since we run inside
asyncio.to_thread() as blocking code, requests is the right tool.
"""

from __future__ import annotations

from datetime import date, timedelta

import requests

BASE = "https://statsapi.mlb.com/api/v1"

# Mapping of common team abbreviations → MLB Stats API team IDs
TEAM_IDS: dict[str, int] = {
    "ARI": 109,
    "ATL": 144,
    "BAL": 110,
    "BOS": 111,
    "CHC": 112,
    "CHW": 145,
    "CWS": 145,
    "CIN": 113,
    "CLE": 114,
    "COL": 115,
    "DET": 116,
    "HOU": 117,
    "KCR": 118,
    "KC": 118,
    "LAA": 108,
    "LAD": 119,
    "MIA": 146,
    "MIL": 158,
    "MIN": 142,
    "NYM": 121,
    "NYY": 147,
    "OAK": 133,
    "PHI": 143,
    "PIT": 134,
    "SDP": 135,
    "SD": 135,
    "SFG": 137,
    "SF": 137,
    "SEA": 136,
    "STL": 138,
    "TBR": 139,
    "TB": 139,
    "TEX": 140,
    "TOR": 141,
    "WSN": 120,
    "WAS": 120,
}

# Friendly position abbrev to full name
POS_NAMES: dict[str, str] = {
    "P": "SP/RP",
    "SP": "SP",
    "RP": "RP",
    "C": "C",
    "1B": "1B",
    "2B": "2B",
    "3B": "3B",
    "SS": "SS",
    "LF": "LF",
    "CF": "CF",
    "RF": "RF",
    "OF": "OF",
    "DH": "DH",
}


def _get(path: str, params: dict | None = None) -> dict:
    """Fetch a MLB Stats API endpoint and return parsed JSON."""
    url = f"{BASE}{path}"
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _team_id(abbrev: str) -> int:
    """Resolve team abbreviation to MLB Stats API team ID. Raises ValueError if unknown."""
    tid = TEAM_IDS.get(abbrev.upper())
    if tid is None:
        valid = ", ".join(sorted({k for k in TEAM_IDS if len(k) <= 3}))
        raise ValueError(f"Unknown team abbreviation {abbrev!r}. Valid: {valid}")
    return tid


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


def fetch_roster(team: str) -> list[dict]:
    """
    Fetch the current active 26-man roster for a team.

    Returns list of dicts: name, position, status.
    Raises ValueError for unknown team.
    """
    tid = _team_id(team)
    data = _get(f"/teams/{tid}/roster", {"rosterType": "active"})
    roster = data.get("roster", [])
    if not roster:
        raise ValueError(f"No active roster data found for {team}.")

    return [
        {
            "name": p.get("person", {}).get("fullName", "Unknown"),
            "pos": p.get("position", {}).get("abbreviation", "?"),
            "status": p.get("status", {}).get("description", "Active"),
        }
        for p in roster
    ]


# ---------------------------------------------------------------------------
# Injury / IL
# ---------------------------------------------------------------------------


def fetch_injuries(team: str) -> list[dict]:
    """
    Fetch players currently on the IL for a team.

    Returns list of dicts: name, pos, note (e.g. "15-Day IL — Left hip inflammation.").
    """
    tid = _team_id(team)
    # The legacy rosterType=injuries endpoint stopped filtering and now returns
    # the active roster, so query the 40-man and filter on IL status codes
    # (D7/D10/D15/D60). Status descriptions look like "Injured 15-Day".
    data = _get(f"/teams/{tid}/roster", {"rosterType": "40Man"})
    roster = data.get("roster", [])

    out: list[dict] = []
    for p in roster:
        status = p.get("status", {}) or {}
        code = status.get("code", "")
        if not code.startswith("D"):
            continue
        stint = status.get("description", "").replace("Injured ", "").strip()
        injury = (p.get("note") or "").strip()
        if stint and injury:
            note = f"{stint} IL — {injury}"
        elif stint:
            note = f"{stint} IL"
        else:
            note = injury or "—"
        out.append(
            {
                "name": p.get("person", {}).get("fullName", "Unknown"),
                "pos": p.get("position", {}).get("abbreviation", "?"),
                "note": note,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def fetch_transactions(team: str, days: int = 7) -> list[dict]:
    """
    Fetch recent roster transactions for a team.

    Returns list of dicts: date, description.
    Raises ValueError for unknown team or no transactions.
    """
    tid = _team_id(team)
    today = date.today()
    start = today - timedelta(days=days)
    data = _get(
        "/transactions",
        {
            "teamId": tid,
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": today.strftime("%Y-%m-%d"),
        },
    )
    transactions = data.get("transactions", [])
    if not transactions:
        raise ValueError(f"No transactions for {team} in the last {days} days.")

    return [
        {
            "date": t.get("date", "?")[:10],
            "desc": t.get("description", "—"),
        }
        for t in sorted(transactions, key=lambda x: x.get("date", ""), reverse=True)
    ]


# ---------------------------------------------------------------------------
# Live scores / schedule
# ---------------------------------------------------------------------------


def fetch_live_scores(team: str) -> list[dict]:
    """
    Fetch today's game(s) for a team with live scores.

    Returns list of game dicts: home, away, score_home, score_away,
    status, inning, outs.
    Raises ValueError if team has no game today.
    """
    tid = _team_id(team)
    today = date.today().strftime("%Y-%m-%d")

    data = _get(
        "/schedule",
        {
            "sportId": 1,
            "date": today,
            "teamId": tid,
            "hydrate": "linescore,probablePitcher(note)",
        },
    )

    dates = data.get("dates", [])
    if not dates:
        raise ValueError(f"{team.upper()} has no game today ({today}).")

    games: list[dict] = []
    for game in dates[0].get("games", []):
        status = game.get("status", {}).get("detailedState", "?")
        home = game["teams"]["home"]
        away = game["teams"]["away"]
        linescore = game.get("linescore", {})
        inning = linescore.get("currentInningOrdinal", "")
        inning_h = linescore.get("inningHalf", "")
        outs = linescore.get("outs", 0)

        games.append(
            {
                "game_pk": game.get("gamePk"),
                "home_team": home["team"]["name"],
                "away_team": away["team"]["name"],
                "home_score": home.get("score", 0),
                "away_score": away.get("score", 0),
                "status": status,
                "inning": f"{inning_h} {inning}".strip() if inning else status,
                "outs": outs,
                "start_time": game.get("gameDate"),
            }
        )
    return games


# ---------------------------------------------------------------------------
# Next game / probable pitchers
# ---------------------------------------------------------------------------


def fetch_next_game(team: str) -> dict:
    """
    Find the next scheduled game for a team, including probable pitchers.

    Returns dict: date, time, home, away, home_probable, away_probable.
    Raises ValueError if no upcoming game found within 14 days.
    """
    tid = _team_id(team)
    today = date.today()
    end = today + timedelta(days=14)

    data = _get(
        "/schedule",
        {
            "sportId": 1,
            "startDate": today.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "teamId": tid,
            "hydrate": "probablePitcher",
        },
    )

    for day in data.get("dates", []):
        for game in day.get("games", []):
            status = game.get("status", {}).get("abstractGameState", "")
            if status in ("Preview", "Scheduled"):
                home = game["teams"]["home"]
                away = game["teams"]["away"]
                home_prob = home.get("probablePitcher", {}).get("fullName", "TBD")
                away_prob = away.get("probablePitcher", {}).get("fullName", "TBD")
                game_time = game.get("gameDate", "")
                return {
                    "date": day["date"],
                    "time": game_time[11:16] + " UTC" if len(game_time) > 16 else "TBD",
                    "home_team": home["team"]["name"],
                    "away_team": away["team"]["name"],
                    "home_probable": home_prob,
                    "away_probable": away_prob,
                }

    raise ValueError(f"No upcoming games found for {team} in the next 14 days.")


# ---------------------------------------------------------------------------
# Player roster (for autocomplete)
# ---------------------------------------------------------------------------

# Reverse lookup: MLB team ID -> abbreviation used everywhere else in the bot.
# Built from TEAM_IDS, preferring the canonical 3-letter form when multiple
# aliases exist (e.g. both "SDP" and "SD" map to 135 — use "SD" because it's
# what baseball-reference and Statcast use).
_CANONICAL_ABBRS: frozenset[str] = frozenset(
    {"ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL", "DET",
     "HOU", "KC", "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "OAK",
     "PHI", "PIT", "SD", "SF", "SEA", "STL", "TB", "TEX", "TOR", "WSN"}
)  # fmt: skip
_TEAM_ID_TO_ABBR: dict[int, str] = {
    tid: abbr for abbr, tid in TEAM_IDS.items() if abbr in _CANONICAL_ABBRS
}


def fetch_players(season: int) -> list[dict]:
    """
    Fetch the full MLB player roster for a given season.

    Returns a list of compact dicts: {id, first, last, team, position}.
    team is the 3-letter abbreviation (e.g. "NYY") or "" if the player's
    currentTeam isn't in the 30 MLB clubs (minor league, free agent, etc.).
    """
    data = _get("/sports/1/players", {"season": season})
    out: list[dict] = []
    for p in data.get("people", []):
        team_id = (p.get("currentTeam") or {}).get("id")
        team_abbr = _TEAM_ID_TO_ABBR.get(team_id, "") if team_id else ""
        out.append(
            {
                "id": p.get("id"),
                "first": (p.get("firstName") or p.get("useName") or "").strip(),
                "last": (p.get("lastName") or "").strip(),
                "team": team_abbr,
                "position": (p.get("primaryPosition") or {}).get("abbreviation", ""),
            }
        )
    return out


def fetch_recent_players(seasons: list[int]) -> list[dict]:
    """
    Fetch rosters for multiple seasons. Callers deduplicate downstream.

    Network calls happen serially; the caller should thread-wrap this for
    asyncio. Failures for individual seasons are logged but don't abort
    the batch — partial data is better than none for autocomplete.
    """
    combined: list[dict] = []
    for season in seasons:
        try:
            combined.extend(fetch_players(season))
        except Exception as exc:
            # Keep going; a single bad season shouldn't kill the whole refresh
            import logging

            logging.getLogger("harry").warning("fetch_players(%d) failed: %s", season, exc)
    return combined
