"""
fangraphs.py — Blocking helpers for the FanGraphs public JSON API.

Uses curl_cffi with Chrome TLS fingerprinting to pass the Cloudflare
challenge that started gating fangraphs.com in mid-2025. No pybaseball
dependency — FanGraphs is fetched directly here.

All functions are synchronous; call via asyncio.to_thread() from async
Discord handlers. No Discord imports.
"""

from __future__ import annotations

import logging
import re
import time

import pandas as pd

from utils import current_year

log = logging.getLogger("harry")

_PITCHING_KEYS = ["W", "L", "ERA", "FIP", "xFIP", "WHIP", "K/9", "BB/9", "HR/9", "WAR", "IP"]
_BATTING_KEYS = ["AVG", "OBP", "SLG", "OPS", "wOBA", "wRC+", "HR", "RBI", "SB", "WAR", "PA"]

_FG_API_URL = "https://www.fangraphs.com/api/leaders/major-league/data"
_FG_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Retry transient failures (5xx + connection errors) before failing.
# A 403 means Cloudflare has noticed our impersonation — no point retrying.
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.75

_CF_BLOCKED_MSG = (
    "FanGraphs is blocking the request right now (probably Cloudflare). Try again in a few minutes."
)


class FangraphsBlockedError(ValueError):
    """Raised when FanGraphs returns 403 — Cloudflare is filtering us.

    Subclasses ValueError so existing `except ValueError` paths in the
    command layer surface the friendly message via str(exc).
    """


def _fmt(val: object) -> str:
    """Format a stat value for display."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if isinstance(val, float):
        return f"{val:.3f}" if val < 10 else f"{val:.1f}"
    return str(val)


def _name_match(df: pd.DataFrame, first: str, last: str) -> pd.DataFrame:
    """Filter FanGraphs DataFrame by player name (case-insensitive)."""
    target = f"{first.lower()} {last.lower()}"
    return df[df["Name"].str.lower() == target]


def fetch_fg_leaderboard(year: int, kind: str, qual: int | str = 1) -> pd.DataFrame:
    """
    Fetch a full FanGraphs season leaderboard via their JSON API.

    Bypasses pybaseball's HTML scraping of leaders-legacy.aspx, which has been
    behind Cloudflare (403 for plain requests) since mid-2025. Uses curl_cffi
    with Chrome TLS fingerprinting to pass the challenge.

    kind: "bat" or "pit".
    qual: minimum PA (bat) or IP (pit). 1 = effectively no minimum.
    Future / empty seasons return an empty DataFrame.
    """
    if kind not in ("bat", "pit"):
        raise ValueError(f"kind must be 'bat' or 'pit', got {kind!r}")

    from curl_cffi import requests as cc_requests

    params = {
        "age": "",
        "pos": "all",
        "stats": kind,
        "lg": "all",
        "qual": qual,
        "season": year,
        "season1": year,
        "ind": 0,
        "team": 0,
        "month": 0,
        "pageitems": 2000,
    }

    resp = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            resp = cc_requests.get(_FG_API_URL, params=params, impersonate="chrome", timeout=20)
        except Exception as exc:
            # curl_cffi raises its own Request/ConnectionError types; treat
            # any network-level failure as retryable.
            if attempt < _RETRY_ATTEMPTS - 1:
                log.warning(
                    "FanGraphs %s (attempt %d/%d), retrying...",
                    type(exc).__name__,
                    attempt + 1,
                    _RETRY_ATTEMPTS,
                )
                time.sleep(_RETRY_BASE_DELAY * (2**attempt))
                continue
            raise

        # Status code may be missing on hand-rolled test fakes — default to 200.
        status = getattr(resp, "status_code", 200)
        if status == 403:
            log.warning("FanGraphs returned 403 — likely Cloudflare gate.")
            raise FangraphsBlockedError(_CF_BLOCKED_MSG)
        if 500 <= status < 600 and attempt < _RETRY_ATTEMPTS - 1:
            log.warning(
                "FanGraphs returned %d (attempt %d/%d), retrying...",
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
    rows = resp.json().get("data") or []
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Name/Team arrive wrapped in HTML anchor tags; strip them.
    for col in ("Name", "Team"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(_FG_HTML_TAG_RE, "", regex=True).str.strip()

    return df


def fetch_player_stats(first: str, last: str, year: int) -> dict:
    """
    Fetch FanGraphs season stats for a player, auto-detecting pitcher vs batter.

    Tries pitching first, then batting.
    Returns dict with keys: type, team, stats.
    Raises ValueError if player not found in either leaderboard.
    """
    pitch_df = fetch_fg_leaderboard(year, "pit")
    if not pitch_df.empty:
        row = _name_match(pitch_df, first, last)
        if not row.empty:
            r = row.iloc[0]
            return {
                "type": "pitcher",
                "team": r.get("Team", "N/A"),
                "stats": {k: _fmt(r.get(k)) for k in _PITCHING_KEYS if k in r.index},
            }

    bat_df = fetch_fg_leaderboard(year, "bat")
    if not bat_df.empty:
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

    pitch_df = fetch_fg_leaderboard(cy, "pit")
    if not pitch_df.empty:
        row = _name_match(pitch_df, first, last)
        if not row.empty:
            r = row.iloc[0]
            return {
                "type": "pitcher",
                "team": r.get("Team", "N/A"),
                "stats": {k: _fmt(r.get(k)) for k in _PITCHING_KEYS if k in r.index},
            }

    bat_df = fetch_fg_leaderboard(cy, "bat")
    if not bat_df.empty:
        row = _name_match(bat_df, first, last)
        if not row.empty:
            r = row.iloc[0]
            return {
                "type": "batter",
                "team": r.get("Team", "N/A"),
                "stats": {k: _fmt(r.get(k)) for k in _BATTING_KEYS if k in r.index},
            }

    raise ValueError(f"No FanGraphs career data found for {first} {last}.")


def fetch_year_fangraphs(yr: int, player_type: str, first: str, last: str) -> pd.DataFrame | None:
    """
    Blocking helper: fetch one year of FanGraphs pitching or batting stats via JSON API.

    Returns DataFrame with a '_year' column, or None on any error.
    Designed to be called via asyncio.to_thread(); concurrency is managed
    by the caller (asyncio.gather + Semaphore).
    """
    try:
        kind = "pit" if player_type == "pitcher" else "bat"
        log.info("FanGraphs: Requesting %s stats for %d...", player_type, yr)

        df = fetch_fg_leaderboard(yr, kind)
        if df.empty:
            log.info("FanGraphs: No valid data for %d (likely future/empty season).", yr)
            return None

        res = _name_match(df, first, last)
        if res.empty:
            return None

        log.info("FanGraphs: Found %s %s for %s in %d.", first, last, player_type, yr)
        res = res.copy()
        res["_year"] = yr
        return res
    except FangraphsBlockedError:
        # Don't swallow — the /career command should report CF block clearly,
        # not show "no data found in 2002-2025" after silently failing every year.
        raise
    except Exception as exc:
        log.exception("FanGraphs Error [%s %d]: %s", player_type, yr, exc)
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
        boards.append(_from_df(fetch_fg_leaderboard(year, "pit")))

    if player_type in ("batter", "auto"):
        boards.append(_from_df(fetch_fg_leaderboard(year, "bat")))

    for board in boards:
        if board:
            return board

    raise ValueError(
        f"Stat '{stat}' not found in FanGraphs leaderboards for {year}. "
        "Try a column name like ERA, WAR, HR, K%, OPS, wRC+, FIP, WHIP."
    )
