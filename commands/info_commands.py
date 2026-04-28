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
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /standings")
            await interaction.followup.send(harry_error(safe_exc_label(exc)))
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
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /schedule")
            await interaction.followup.send(harry_error(safe_exc_label(exc)))
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
