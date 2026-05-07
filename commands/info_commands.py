"""
commands/info_commands.py — /standings, /schedule, /hope, and /abs slash commands.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from abs import (
    fetch_league_leaders,
    fetch_team_summary,
    fetch_team_top_challengers,
)
from abs import (
    fetch_player as fetch_abs_player,
)
from commands.autocomplete import first_name_autocomplete, last_name_autocomplete
from persona import harry_error, safe_exc_label
from playoff_hope import fetch_team_hope, hex_to_rgb, render_last_n_strip
from statcast import fetch_schedule, fetch_standings
from utils import current_season

log = logging.getLogger("harry")

# Common MLB team abbreviations shown to the user
TEAM_ABBREVS = "e.g. DET, CLE, MIN, CHW, KCR, NYY, BOS, LAD, SFG, HOU ..."


class InfoCommands(commands.Cog):
    """League info commands — standings and schedule."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -----------------------------------------------------------------------
    # /standings
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="standings",
        description="Show MLB division standings for a given season.",
    )
    @app_commands.describe(year="Season year (e.g. 2024). Defaults to current season.")
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def standings(
        self,
        interaction: discord.Interaction,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        await interaction.response.defer(thinking=True)
        log.info("/standings called: %d", year)

        try:
            divisions: list[tuple[str, str]] = await asyncio.to_thread(fetch_standings, year)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("Unexpected error in /standings")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🏆 MLB Standings — {year}",
            color=discord.Color.from_rgb(0, 40, 104),
        )
        for division_name, table in divisions:
            embed.add_field(name=division_name, value=table, inline=False)
        embed.set_footer(text="Data: Baseball Reference via pybaseball")

        await interaction.followup.send(embed=embed)
        log.info("/standings completed: %d", year)

    # -----------------------------------------------------------------------
    # /schedule
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="schedule",
        description="Show a team's recent results and upcoming games.",
    )
    @app_commands.describe(
        team=f"Team abbreviation — {TEAM_ABBREVS}",
        year="Season year (e.g. 2024). Defaults to current season.",
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def schedule(
        self,
        interaction: discord.Interaction,
        team: str,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        await interaction.response.defer(thinking=True)

        team_upper = team.strip().upper()
        log.info("/schedule called: %s %d", team_upper, year)

        try:
            past, upcoming = await asyncio.to_thread(fetch_schedule, team_upper, year)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("Unexpected error in /schedule")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📅 {team_upper} Schedule — {year}",
            color=discord.Color.from_rgb(200, 16, 46),
        )
        if past:
            embed.add_field(name="Recent Results", value=past, inline=False)
        if upcoming:
            embed.add_field(name="Upcoming Games", value=upcoming, inline=False)
        embed.set_footer(text="Data: Baseball Reference via pybaseball")

        await interaction.followup.send(embed=embed)
        log.info("/schedule completed: %s %d", team_upper, year)

    # -----------------------------------------------------------------------
    # /hope
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="hope",
        description="Show a team's playoff odds — pulled live from FanGraphs.",
    )
    @app_commands.describe(team=f"Team abbreviation or name — {TEAM_ABBREVS}")
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def hope(self, interaction: discord.Interaction, team: str) -> None:
        await interaction.response.defer(thinking=True)
        log.info("/hope called: %s", team)

        try:
            data = await asyncio.to_thread(fetch_team_hope, team)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("Unexpected error in /hope")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        playoff_pct = data["playoff_pct"]
        # 25% threshold — matches mlbplayoffhope.com's HOPE/NOPE convention.
        label = "HOPE" if playoff_pct >= 25 else "NOPE"
        title = f"🌅 {data['name']} — {label} {playoff_pct:.1f}%"

        gb = data["gb"]
        gb_str = "—" if gb == 0 else (f"+{abs(gb):g}" if gb < 0 else f"-{gb:g}")
        record_line = (
            f"**Record:** {data['wins']}-{data['losses']} ({data['win_pct']:.3f})  •  "
            f"**GB:** {gb_str}"
        )
        proj_line = (
            f"**Projected:** {data['proj_w']:.1f}-{data['proj_l']:.1f}  •  "
            f"**Rest-of-season:** {data['ros_pct']:.1f}%"
        )

        embed = discord.Embed(
            title=title,
            description=f"{record_line}\n{proj_line}",
            color=discord.Color.from_rgb(*hex_to_rgb(data["primary_color"])),
        )
        last_strip = render_last_n_strip(data.get("last_results") or [])
        if last_strip:
            embed.add_field(
                name=f"Last {len(data['last_results'])}  (🟩 home W · 🟥 home L · 🟢 away W · 🔴 away L)",
                value=last_strip,
                inline=False,
            )
        embed.add_field(name="Make Playoffs", value=f"{data['playoff_pct']:.1f}%", inline=True)
        embed.add_field(name="Win Division", value=f"{data['division_pct']:.1f}%", inline=True)
        embed.add_field(name="Win Wild Card", value=f"{data['wildcard_pct']:.1f}%", inline=True)
        embed.add_field(name="Win World Series", value=f"{data['ws_pct']:.2f}%", inline=True)
        embed.add_field(
            name="Further material",
            value=f"[mlbplayoffhope.com — {data['name']}]({data['url']})",
            inline=False,
        )
        footer = "Data: FanGraphs playoff odds"
        if data.get("last_updated"):
            footer = f"{footer} • Fetched {data['last_updated']}"
        embed.set_footer(text=footer)

        await interaction.followup.send(embed=embed)
        log.info("/hope completed: %s (%.2f%%)", data["abbr"], playoff_pct)

    # -----------------------------------------------------------------------
    # /abs — team summary or league leaders
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="abs",
        description="Show ABS challenge stats — team summary, or league leaders if no team.",
    )
    @app_commands.describe(
        team=f"Team abbreviation. Omit for league leaders. {TEAM_ABBREVS}",
        year="Season year. Defaults to current season.",
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def abs_cmd(
        self,
        interaction: discord.Interaction,
        team: str | None = None,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        if err := _validate_abs_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        log.info("/abs called: team=%s year=%d", team, year)

        try:
            if team:
                embed = await asyncio.to_thread(_build_team_embed, team, year)
            else:
                embed = await asyncio.to_thread(_build_league_embed, year)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("Unexpected error in /abs")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /playerabs — single-player challenge view
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="playerabs",
        description="Show ABS challenge stats for a single player.",
    )
    @app_commands.describe(
        first_name="Player first name",
        last_name="Player last name",
        year="Season year. Defaults to current season.",
    )
    @app_commands.autocomplete(
        first_name=first_name_autocomplete,
        last_name=last_name_autocomplete,
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def playerabs(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        if err := _validate_abs_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        log.info("/playerabs called: %s %s %d", first_name, last_name, year)

        try:
            embed = await asyncio.to_thread(_build_player_embed, first_name, last_name, year)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("Unexpected error in /playerabs")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /abs embed builders — pure functions, run in a worker thread.
# ---------------------------------------------------------------------------

_ABS_COLOR = discord.Color.from_rgb(0, 122, 204)  # umpire-blue
_ABS_FIRST_YEAR = 2026  # ABS challenge system debuted in MLB this season


def _validate_abs_year(year: int) -> str | None:
    if year < _ABS_FIRST_YEAR:
        return f"ABS challenges started in {_ABS_FIRST_YEAR} — nothing to call before then, pal."
    return None


def _fmt_rate(num: float | None) -> str:
    if num is None:
        return "—"
    return f"{num * 100:.1f}%"


def _build_team_embed(team: str, year: int) -> discord.Embed:
    summary = fetch_team_summary(team, year)
    top = fetch_team_top_challengers(team, year, limit=5)

    name = summary.get("entity_name") or team.upper()
    abbr = summary.get("team_abbr") or team.upper()

    # Offensive (their hitters challenging) and defensive (their pitcher/catcher).
    n_off = int(summary.get("n_challenges_off") or 0)
    over_off = int(summary.get("n_overturns_off") or 0)
    rate_off = summary.get("rate_overturns_off")
    n_def = int(summary.get("n_challenges_def") or 0)
    over_def = int(summary.get("n_overturns_def") or 0)
    rate_def = summary.get("rate_overturns_def")
    k_flip = int(
        (summary.get("n_strikeouts_flip_off") or 0) + (summary.get("n_strikeouts_flip_def") or 0)
    )
    bb_flip = int((summary.get("n_walks_flip_off") or 0) + (summary.get("n_walks_flip_def") or 0))

    embed = discord.Embed(
        title=f"⚖️ {name} — ABS Challenges {year}",
        description=(
            f"**Total challenges:** {n_off + n_def}  "
            f"({n_off + n_def - over_off - over_def} stood, {over_off + over_def} overturned)\n"
            f"**Strikeouts flipped:** {k_flip}  •  **Walks flipped:** {bb_flip}"
        ),
        color=_ABS_COLOR,
    )
    embed.add_field(
        name="Offense (batters)",
        value=f"{n_off} chal • {over_off} won • {_fmt_rate(rate_off)}",
        inline=True,
    )
    embed.add_field(
        name="Defense (P / C)",
        value=f"{n_def} chal • {over_def} won • {_fmt_rate(rate_def)}",
        inline=True,
    )
    if top:
        rows = "\n".join(
            f"{int(r.get('n_challenges') or 0):>3} chal "
            f"{int(r.get('n_overturns') or 0):>2}W  "
            f"{_fmt_rate(r.get('rate_overturns')):>6}  "
            f"{r.get('entity_name')} ({r.get('role')})"
            for r in top
        )
        embed.add_field(name="Top challengers", value=f"```\n{rows}\n```", inline=False)
    embed.set_footer(text=f"Data: Baseball Savant • {abbr}")
    return embed


def _build_player_embed(first: str, last: str, year: int) -> discord.Embed:
    data = fetch_abs_player(first, last, year)
    totals = data["totals"]
    rate = (totals["n_overturns"] / totals["n_challenges"]) if totals["n_challenges"] else None

    embed = discord.Embed(
        title=f"⚖️ {data['name']} — ABS Challenges {year}",
        description=(
            f"**{int(totals['n_challenges'])} challenges**  •  "
            f"{int(totals['n_overturns'])} overturned  •  "
            f"{int(totals['n_confirms'])} confirmed  •  "
            f"**{_fmt_rate(rate)}** success"
        ),
        color=_ABS_COLOR,
    )
    embed.add_field(
        name="Strikeouts flipped", value=str(int(totals["n_strikeouts_flip"])), inline=True
    )
    embed.add_field(name="Walks flipped", value=str(int(totals["n_walks_flip"])), inline=True)
    embed.add_field(name="Team", value=data.get("team_abbr") or "—", inline=True)

    # Per-role breakdown when the player challenged from more than one spot.
    if len(data["roles"]) > 1:
        rows = "\n".join(
            f"{r['role']:<8} {int(r.get('n_challenges') or 0):>3} chal  "
            f"{int(r.get('n_overturns') or 0):>2}W  {_fmt_rate(r.get('rate_overturns'))}"
            for r in data["roles"]
        )
        embed.add_field(name="By role", value=f"```\n{rows}\n```", inline=False)

    embed.set_footer(text="Data: Baseball Savant")
    return embed


def _build_league_embed(year: int) -> discord.Embed:
    leaders = fetch_league_leaders(year, limit=10, min_challenges=3)
    if not leaders:
        raise ValueError(f"No ABS challenge data available yet for {year}.")

    rows = "\n".join(
        f"{i:>2}. {_fmt_rate(r.get('rate_overturns')):>6}  "
        f"{int(r.get('n_overturns') or 0):>2}/{int(r.get('n_challenges') or 0):<2}  "
        f"{r.get('entity_name')} ({r.get('team_abbr')}, {r.get('role')})"
        for i, r in enumerate(leaders, 1)
    )
    embed = discord.Embed(
        title=f"⚖️ ABS Challenge Leaders — {year}",
        description=f"Top success rates league-wide (min 3 challenges)\n```\n{rows}\n```",
        color=_ABS_COLOR,
    )
    embed.set_footer(text="Data: Baseball Savant")
    return embed
