"""
playoff_hope.py — FanGraphs playoff odds.

Source of truth: https://www.fangraphs.com/standings/playoff-odds/fg/div

That page is a Next.js app — the entire dataset is server-rendered into a
<script id="__NEXT_DATA__"> JSON blob (a hydrated react-query cache). We
fetch the page through curl_cffi with Chrome TLS fingerprinting to pass
the Cloudflare gate (same pattern as fangraphs.py), pull the
"playoff-odds" query out of the dehydrated state, and return one row per
team with the fields we display: record, projected record, and the
make-playoffs / win-division / win-WS chances.

The companion site mlbplayoffhope.com is referenced only as a "further
material" link in the embed — we don't read its API.

Synchronous; call via asyncio.to_thread() from async Discord handlers.
No Discord imports.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time

from fangraphs import FangraphsBlockedError
from mlb_api import fetch_recent_results

log = logging.getLogger("harry")

FG_ODDS_URL = "https://www.fangraphs.com/standings/playoff-odds/fg/div"
MLBPLAYOFFHOPE_URL = "https://mlbplayoffhope.com"

# Match Cloudflare-friendly knobs to fangraphs.py: 3 attempts, exp backoff.
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.75
_REQUEST_TIMEOUT = 20

# The full season odds page is ~300 KB and updates a few times a day. A
# 10-minute TTL matches mlbplayoffhope.com's refresh cadence and keeps
# /hope spam from re-fetching repeatedly.
_CACHE_TTL_SECONDS = 600

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)

_CF_BLOCKED_MSG = (
    "FanGraphs is blocking the request right now (probably Cloudflare). Try again in a few minutes."
)

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

# FG abbName → mlb_api.TEAM_IDS key. They line up except for the Athletics:
# FG calls them ATH (current branding), MLB Stats API still uses OAK.
_FG_TO_MLB_ABBR: dict[str, str] = {"ATH": "OAK"}

# Emoji squares for the last-N strip. Big squares for home games (you're at
# home, take up space), circles for away games — keeps the row easy to scan
# without a legend.
_RESULT_EMOJI: dict[tuple[bool, str], str] = {
    (True, "W"): "🟩",
    (True, "L"): "🟥",
    (False, "W"): "🟢",
    (False, "L"): "🔴",
    (True, "P"): "⚪",
    (False, "P"): "⚪",
}


# Public team branding used only for embed color + the mlbplayoffhope.com
# detail-page slug. Colors are MLB's published primary brand colors;
# slugs match mlbplayoffhope.com's routing scheme so the "further
# material" link lands on the right team page.
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
    """Thread-safe TTL cache for the parsed FanGraphs odds rows."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict] | None = None
        self._fetched_at_str: str = ""
        self._fetched_at: float = 0.0

    def get(self) -> tuple[dict[str, dict], str]:
        with self._lock:
            now = time.monotonic()
            if self._rows is not None and (now - self._fetched_at) < _CACHE_TTL_SECONDS:
                return self._rows, self._fetched_at_str

            html = _fetch_html(FG_ODDS_URL)
            rows = _parse_odds(html)
            if not rows:
                raise ValueError(
                    "FanGraphs returned the playoff odds page but no team rows "
                    "were found — site layout may have changed."
                )
            self._rows = rows
            # FG embeds the playoff-odds query date in its hash; also stamp wall
            # time for the embed footer.
            self._fetched_at_str = time.strftime("%Y-%m-%d %H:%M %Z", time.localtime())
            self._fetched_at = now
            return self._rows, self._fetched_at_str

    def clear(self) -> None:
        with self._lock:
            self._rows = None
            self._fetched_at_str = ""
            self._fetched_at = 0.0


_cache = _Cache()


def _fetch_html(url: str) -> str:
    """Fetch a FanGraphs page through Chrome-impersonated curl_cffi.

    Mirrors the retry/blocking behavior of fangraphs.fetch_fg_leaderboard so
    Cloudflare 403s become a clean FangraphsBlockedError and 5xx/connection
    failures get a couple of exponential-backoff retries.
    """
    from curl_cffi import requests as cc_requests

    resp = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            resp = cc_requests.get(url, impersonate="chrome", timeout=_REQUEST_TIMEOUT)
        except Exception as exc:
            if attempt < _RETRY_ATTEMPTS - 1:
                log.warning(
                    "FanGraphs odds %s (attempt %d/%d), retrying...",
                    type(exc).__name__,
                    attempt + 1,
                    _RETRY_ATTEMPTS,
                )
                time.sleep(_RETRY_BASE_DELAY * (2**attempt))
                continue
            raise

        status = getattr(resp, "status_code", 200)
        if status == 403:
            log.warning("FanGraphs odds returned 403 — likely Cloudflare gate.")
            raise FangraphsBlockedError(_CF_BLOCKED_MSG)
        if 500 <= status < 600 and attempt < _RETRY_ATTEMPTS - 1:
            log.warning(
                "FanGraphs odds returned %d (attempt %d/%d), retrying...",
                status,
                attempt + 1,
                _RETRY_ATTEMPTS,
            )
            time.sleep(_RETRY_BASE_DELAY * (2**attempt))
            continue
        break

    if resp is None:
        raise RuntimeError("unreachable")
    resp.raise_for_status()
    text = getattr(resp, "text", None)
    if text is None:
        # curl_cffi returns bytes via .content; decode if needed.
        text = resp.content.decode("utf-8", errors="replace")
    return text


def _parse_odds(html: str) -> dict[str, dict]:
    """Pull the playoff-odds rows out of the embedded __NEXT_DATA__ blob.

    FG dehydrates a react-query cache into the page; one of the queries
    has hash starting with "playoff-odds". Index by abbName for O(1)
    team lookup later.
    """
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}

    queries = (
        payload.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    )
    rows: list[dict] = []
    for q in queries:
        qhash = q.get("queryHash") or ""
        # queryHash is a JSON-encoded array — string-search for "playoff-odds"
        # works whether it's still encoded or already a list.
        flat = qhash if isinstance(qhash, str) else json.dumps(qhash)
        if "playoff-odds" not in flat:
            continue
        data = q.get("state", {}).get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict) and "abbName" in data[0]:
            rows = data
            break

    return {row["abbName"]: row for row in rows if row.get("abbName")}


def _resolve_abbr(query: str, rows: dict[str, dict]) -> str | None:
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


def fetch_team_hope(team: str) -> dict:
    """
    Look up one team's playoff odds from FanGraphs.

    `team` accepts an abbreviation (DET, NYY), an alias (CWS, OAK, TB),
    or a unique team-name substring (red sox, blue jays).

    Returns a dict shaped for the /hope embed:
        abbr, name, slug, primary_color, url,
        wins, losses, win_pct, gb,
        proj_w, proj_l, ros_pct,
        playoff_pct, division_pct, wildcard_pct, ws_pct,
        last_results (list of dicts), last_updated

    Raises ValueError if the team can't be resolved or the page can't be parsed.
    """
    rows, last_updated = _cache.get()
    abbr = _resolve_abbr(team, rows)
    if abbr is None:
        valid = ", ".join(sorted(rows.keys()))
        raise ValueError(f"Unknown team {team!r}. Valid: {valid}.")

    row = rows[abbr]
    end = row.get("endData") or {}
    brand = _TEAM_BRANDS.get(abbr, {"slug": "", "primary_color": "#0C2340"})
    slug = brand["slug"]
    mlb_abbr = _FG_TO_MLB_ABBR.get(abbr, abbr)

    # MLB Stats API call is best-effort: if it fails, the embed degrades to no
    # last-N strip rather than failing the whole /hope command.
    try:
        last_results = fetch_recent_results(mlb_abbr, n=10)
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
        "proj_w": float(end.get("ExpW", 0.0) or 0.0),
        "proj_l": float(end.get("ExpL", 0.0) or 0.0),
        "ros_pct": _pct(end.get("rosW")),
        "playoff_pct": _pct(end.get("poffTitle")),
        "division_pct": _pct(end.get("divTitle")),
        "wildcard_pct": _pct(end.get("wcTitle")),
        "ws_pct": _pct(end.get("wsWin")),
        "last_results": last_results,
        "last_updated": last_updated,
    }


def render_last_n_strip(results: list[dict]) -> str:
    """Turn a fetch_recent_results list into an emoji strip (oldest → newest).

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
