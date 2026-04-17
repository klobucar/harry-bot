"""
commands/visual_commands.py — /spraychart command.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from commands.autocomplete import first_name_autocomplete, last_name_autocomplete
from persona import harry_error
from statcast import fetch_hitter_hotzones, fetch_spray_chart, fetch_stadium_info, resolve_player_id
from utils import current_season, validate_statcast_year

log = logging.getLogger("harry")

# Common team stadium names accepted by pybaseball's spraychart()
STADIUM_HELP = (
    "Team name for stadium overlay, e.g. 'tigers', 'guardians', 'yankees'. Use 'generic' if unsure."
)


class VisualCommands(commands.Cog):
    """Visual plot commands beyond strike zones."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="spraychart",
        description="Plot where a batter hits the ball on a stadium spray chart.",
    )
    @app_commands.describe(
        first_name="Batter's first name",
        last_name="Batter's last name",
        year="Season year (e.g. 2024). Defaults to current season.",
        team_stadium="Stadium to use, e.g. 'tigers', 'yankees', 'generic'",
    )
    @app_commands.autocomplete(
        first_name=first_name_autocomplete,
        last_name=last_name_autocomplete,
    )
    async def spraychart(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        year: int | None = None,
        team_stadium: str = "generic",
    ) -> None:
        year = year if year is not None else current_season()
        if err := validate_statcast_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        stadium = team_stadium.strip().lower()
        log.info("/spraychart called: %s (%d) @ %s", player_name, year, stadium)

        try:
            player_id: int | None = await asyncio.to_thread(
                resolve_player_id, first_name.strip(), last_name.strip()
            )
            if player_id is None:
                await interaction.followup.send(harry_error(f"No MLBAM ID for {player_name!r}."))
                return

            buf: BytesIO = await asyncio.to_thread(
                fetch_spray_chart, player_id, year, player_name, stadium
            )

        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /spraychart")
            await interaction.followup.send(harry_error(str(exc)))
            return

        file = discord.File(fp=buf, filename="spraychart.png")
        embed = discord.Embed(
            title=f"💥 Spray Chart: {player_name}",
            description=(
                f"**Season:** {year}\n**Stadium:** {stadium.title()}\n"
                "All batted ball events, colored by outcome."
            ),
            color=discord.Color.from_rgb(255, 140, 0),  # orange
        )
        embed.set_image(url="attachment://spraychart.png")
        embed.set_footer(text="Data: Baseball Savant / Statcast via pybaseball")

        await interaction.followup.send(embed=embed, file=file)
        log.info("/spraychart completed for %s (%d)", player_name, year)

    @app_commands.command(
        name="hotzones",
        description="Show a batter's performance (BA) across the strike zone as a 3x3 thermal grid.",
    )
    @app_commands.describe(
        first_name="Batter's first name",
        last_name="Batter's last name",
        year="Season year (e.g. 2024). Defaults to current season.",
    )
    @app_commands.autocomplete(
        first_name=first_name_autocomplete,
        last_name=last_name_autocomplete,
    )
    async def hotzones(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        if err := validate_statcast_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        log.info("/hotzones called: %s (%d)", player_name, year)

        try:
            player_id: int | None = await asyncio.to_thread(
                resolve_player_id, first_name.strip(), last_name.strip()
            )
            if player_id is None:
                await interaction.followup.send(harry_error(f"No MLBAM ID for {player_name!r}."))
                return

            buf: BytesIO = await asyncio.to_thread(
                fetch_hitter_hotzones, player_id, year, player_name
            )

        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /hotzones")
            await interaction.followup.send(harry_error(str(exc)))
            return

        file = discord.File(fp=buf, filename="hotzones.png")
        embed = discord.Embed(
            title=f"🔥 Hitter Hot Zones: {player_name}",
            description=(
                f"**Season:** {year}\nStrike zone (1-9) colored by Batting Average (Hits/AB)."
            ),
            color=discord.Color.from_rgb(220, 20, 60),  # crimson
        )
        embed.set_image(url="attachment://hotzones.png")
        embed.set_footer(text="Data: Baseball Savant / Statcast via pybaseball")

        await interaction.followup.send(embed=embed, file=file)
        log.info("/hotzones completed for %s (%d)", player_name, year)

    @app_commands.command(
        name="stadium",
        description="Show a ballpark's name, location, and visual outline.",
    )
    @app_commands.describe(team="Team abbreviation or name, e.g. DET, Yankees, Fenway")
    async def stadium(
        self,
        interaction: discord.Interaction,
        team: str,
    ) -> None:
        await interaction.response.defer(thinking=True)
        log.info("/stadium called: %s", team)

        try:
            info = await asyncio.to_thread(fetch_stadium_info, team)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /stadium")
            await interaction.followup.send(harry_error(str(exc)))
            return

        file = discord.File(fp=info["image"], filename="stadium.png")
        embed = discord.Embed(
            title=f"🏟️ {info['name']}",
            description=f"**Location:** {info['location']}",
            color=discord.Color.from_rgb(34, 139, 34),  # forest green
        )
        embed.set_image(url="attachment://stadium.png")
        embed.set_footer(text="Data: Baseball Savant / pybaseball")

        await interaction.followup.send(embed=embed, file=file)
