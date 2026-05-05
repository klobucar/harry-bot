"""
commands/info_commands.py — /standings and /schedule slash commands.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

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
