"""
playoff_hope.py — FanGraphs playoff odds for /hope.

The data layer (scraping fangraphs.com's playoff-odds page through curl_cffi
and parsing the Next.js __NEXT_DATA__ blob) now lives in
``bigleague.playoff_odds`` and returns a polars frame. This module keeps the
Discord-presentation concerns: team-name resolution, brand colors/slugs, the
last-N emoji strip, and the embed-shaped dict. ``fetch_team_hope`` is now
``async`` and awaited directly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from bigleague import playoff_odds
from bigleague.fangraphs import FangraphsBlockedError  # noqa: F401  (re-exported for callers)
from bigleague.mlb import recent_results

log = logging.getLogger("harry")

MLBPLAYOFFHOPE_URL = "https://mlbplayoffhope.com"

# The full season odds page updates a few times a day. A 10-minute TTL keeps
# /hope spam from re-fetching repeatedly.
_CACHE_TTL_SECONDS = 600

# User input → FanGraphs abbName. FG uses standard 3-letter abbrs;
# normalize the few common variants users type.
_TEAM_ALIASES: dict[str, str] = {
    "KC": "KCR",
    "SD": "SDP",
    "SF": "SFG",
    "TB": "TBR",
    "WAS": "WSN",
    "WSH": "WSN",
    "CWS": "CHW",
    "OAK": "ATH",
}

# FG abbName → MLB Stats API abbr. They line up except for the Athletics:
# FG calls them ATH (current branding), MLB Stats API still uses OAK.
_FG_TO_MLB_ABBR: dict[str, str] = {"ATH": "OAK"}

# Emoji squares for the last-N strip. Big squares for home games, circles for
# away games — keeps the row easy to scan without a legend.
_RESULT_EMOJI: dict[tuple[bool, str], str] = {
    (True, "W"): "🟩",
    (True, "L"): "🟥",
    (False, "W"): "🟢",
    (False, "L"): "🔴",
    (True, "P"): "⚪",
    (False, "P"): "⚪",
}

# Public team branding for embed color + the mlbplayoffhope.com slug.
_TEAM_BRANDS: dict[str, dict[str, str]] = {
    "ARI": {"slug": "diamondbacks", "primary_color": "#A71930"},
    "ATH": {"slug": "athletics", "primary_color": "#003831"},
    "ATL": {"slug": "braves", "primary_color": "#13274F"},
    "BAL": {"slug": "orioles", "primary_color": "#DF4601"},
    "BOS": {"slug": "redsox", "primary_color": "#BD3039"},
    "CHC": {"slug": "cubs", "primary_color": "#0E3386"},
    "CHW": {"slug": "whitesox", "primary_color": "#27251F"},
    "CIN": {"slug": "reds", "primary_color": "#C6011F"},
    "CLE": {"slug": "guardians", "primary_color": "#00385D"},
    "COL": {"slug": "rockies", "primary_color": "#333366"},
    "DET": {"slug": "tigers", "primary_color": "#0C2340"},
    "HOU": {"slug": "astros", "primary_color": "#002D62"},
    "KCR": {"slug": "royals", "primary_color": "#004687"},
    "LAA": {"slug": "angels", "primary_color": "#BA0021"},
    "LAD": {"slug": "dodgers", "primary_color": "#005A9C"},
    "MIA": {"slug": "marlins", "primary_color": "#00A3E0"},
    "MIL": {"slug": "brewers", "primary_color": "#12284B"},
    "MIN": {"slug": "twins", "primary_color": "#002B5C"},
    "NYM": {"slug": "mets", "primary_color": "#002D72"},
    "NYY": {"slug": "yankees", "primary_color": "#003087"},
    "PHI": {"slug": "phillies", "primary_color": "#E81828"},
    "PIT": {"slug": "pirates", "primary_color": "#27251F"},
    "SDP": {"slug": "padres", "primary_color": "#2F241D"},
    "SEA": {"slug": "mariners", "primary_color": "#0C2C56"},
    "SFG": {"slug": "giants", "primary_color": "#FD5A1E"},
    "STL": {"slug": "cardinals", "primary_color": "#C41E3A"},
    "TBR": {"slug": "rays", "primary_color": "#092C5C"},
    "TEX": {"slug": "rangers", "primary_color": "#003278"},
    "TOR": {"slug": "bluejays", "primary_color": "#134A8E"},
    "WSN": {"slug": "nationals", "primary_color": "#AB0003"},
}


class _Cache:
    """Async TTL cache for the parsed FanGraphs odds rows (keyed by abbName)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._rows: dict[str, dict[str, Any]] | None = None
        self._fetched_at_str: str = ""
        self._fetched_at: float = 0.0

    async def get(self) -> tuple[dict[str, dict[str, Any]], str]:
        async with self._lock:
            now = time.monotonic()
            if self._rows is not None and (now - self._fetched_at) < _CACHE_TTL_SECONDS:
                return self._rows, self._fetched_at_str

            df = await playoff_odds()
            rows = {r["abbName"]: r for r in df.iter_rows(named=True) if r.get("abbName")}
            if not rows:
                raise ValueError(
                    "FanGraphs returned the playoff odds page but no team rows "
                    "were found — site layout may have changed."
                )
            self._rows = rows
            self._fetched_at_str = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime())
            self._fetched_at = now
            return self._rows, self._fetched_at_str

    def clear(self) -> None:
        self._rows = None
        self._fetched_at_str = ""
        self._fetched_at = 0.0


_cache = _Cache()


def _resolve_abbr(query: str, rows: dict[str, dict[str, Any]]) -> str | None:
    """Map user input to an FG abbName key (or None)."""
    q = query.strip()
    if not q:
        return None
    q_up = q.upper()
    if q_up in rows:
        return q_up
    aliased = _TEAM_ALIASES.get(q_up)
    if aliased and aliased in rows:
        return aliased

    # Match against shortName ("Tigers", "Red Sox", etc.) — case-insensitive,
    # accept exact match or a unique substring ("red sox" → BOS, "jays" → TOR).
    q_low = q.lower()
    exact = [abbr for abbr, row in rows.items() if (row.get("shortName") or "").lower() == q_low]
    if len(exact) == 1:
        return exact[0]
    contains = [abbr for abbr, row in rows.items() if q_low in (row.get("shortName") or "").lower()]
    if len(contains) == 1:
        return contains[0]
    return None


def _pct(x: float | int | str | None) -> float:
    """FG stores fractions (0-1); turn into a 0-100 percent for display."""
    if x is None:
        return 0.0
    try:
        return float(x) * 100.0
    except TypeError, ValueError:
        return 0.0


async def fetch_team_hope(team: str) -> dict:
    """
    Look up one team's playoff odds from FanGraphs (via bigleague).

    `team` accepts an abbreviation (DET, NYY), an alias (CWS, OAK, TB),
    or a unique team-name substring (red sox, blue jays).

    Returns a dict shaped for the /hope embed. Raises ValueError if the team
    can't be resolved or the page can't be parsed; FangraphsBlockedError on
    a Cloudflare 403.
    """
    rows, last_updated = await _cache.get()
    abbr = _resolve_abbr(team, rows)
    if abbr is None:
        valid = ", ".join(sorted(rows.keys()))
        raise ValueError(f"Unknown team {team!r}. Valid: {valid}.")

    row = rows[abbr]
    brand = _TEAM_BRANDS.get(abbr, {"slug": "", "primary_color": "#0C2340"})
    slug = brand["slug"]
    mlb_abbr = _FG_TO_MLB_ABBR.get(abbr, abbr)

    # MLB Stats API call is best-effort: if it fails, the embed degrades to no
    # last-N strip rather than failing the whole /hope command.
    try:
        last_results = await recent_results(mlb_abbr, n=10)
    except Exception as exc:  # pragma: no cover - network failure path
        log.warning("recent results lookup failed for %s: %s", mlb_abbr, exc)
        last_results = []

    return {
        "abbr": abbr,
        "name": row.get("shortName", abbr),
        "slug": slug,
        "primary_color": brand["primary_color"],
        "url": f"{MLBPLAYOFFHOPE_URL}/#{slug}" if slug else MLBPLAYOFFHOPE_URL,
        "wins": int(row.get("W", 0) or 0),
        "losses": int(row.get("L", 0) or 0),
        "win_pct": float(row.get("Wpct", 0.0) or 0.0),
        "gb": row.get("GB", 0),
        "proj_w": float(row.get("exp_w", 0.0) or 0.0),
        "proj_l": float(row.get("exp_l", 0.0) or 0.0),
        "ros_pct": _pct(row.get("ros_pct")),
        "playoff_pct": _pct(row.get("playoff_pct")),
        "division_pct": _pct(row.get("division_pct")),
        "wildcard_pct": _pct(row.get("wildcard_pct")),
        "ws_pct": _pct(row.get("ws_pct")),
        "last_results": last_results,
        "last_updated": last_updated,
    }


def render_last_n_strip(results: list[dict]) -> str:
    """Turn a recent-results list into an emoji strip (oldest → newest).

    🟩 = home win, 🟥 = home loss, 🟢 = away win, 🔴 = away loss, ⚪ = postponed.
    """
    return "".join(
        _RESULT_EMOJI.get((bool(g.get("is_home")), str(g.get("result", ""))), "⬛") for g in results
    )


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse '#RRGGBB' into an (r, g, b) tuple. Falls back to MLB navy on error."""
    s = (hex_color or "").strip().lstrip("#")
    if len(s) != 6:
        return (0, 40, 104)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 40, 104)
