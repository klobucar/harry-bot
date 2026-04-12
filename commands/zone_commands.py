"""
commands/zone_commands.py — /strikezone and /battedzone slash commands.
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

from persona import harry_error
from statcast import fetch_batter_zone, fetch_pitcher_zone, resolve_player_id
from utils import validate_statcast_year

log = logging.getLogger("harry")


class ZoneCommands(commands.Cog):
    """Strike-zone plot commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -----------------------------------------------------------------------
    # /strikezone
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="strikezone",
        description="Plot a pitcher's strike zone for a given season.",
    )
    @app_commands.describe(
        first_name="Pitcher's first name",
        last_name="Pitcher's last name",
        year="Season year (e.g. 2023)",
    )
    async def strikezone(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        year: int,
    ) -> None:
        if err := validate_statcast_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        log.info("/strikezone called: %s (%d)", player_name, year)

        try:
            player_id: int | None = await asyncio.to_thread(
                resolve_player_id, first_name.strip(), last_name.strip()
            )
            if player_id is None:
                await interaction.followup.send(harry_error(f"No MLBAM ID for {player_name!r}."))
                return

            buf: BytesIO = await asyncio.to_thread(fetch_pitcher_zone, player_id, year, player_name)

        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /strikezone")
            await interaction.followup.send(harry_error(str(exc)))
            return

        file = discord.File(fp=buf, filename="strikezone.png")
        embed = discord.Embed(
            title=f"⚾ Strike Zone: {player_name}",
            description=f"**Season:** {year}\n**Player ID (MLBAM):** {player_id}",
            color=discord.Color.from_rgb(0, 40, 104),
        )
        embed.set_image(url="attachment://strikezone.png")
        embed.set_footer(text="Data: Baseball Savant / Statcast via pybaseball")

        await interaction.followup.send(embed=embed, file=file)
        log.info("/strikezone completed for %s (%d)", player_name, year)

    # -----------------------------------------------------------------------
    # /battedzone
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="battedzone",
        description="Plot all pitches thrown to a batter during a season.",
    )
    @app_commands.describe(
        first_name="Batter's first name",
        last_name="Batter's last name",
        year="Season year (e.g. 2023)",
    )
    async def battedzone(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        year: int,
    ) -> None:
        if err := validate_statcast_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        log.info("/battedzone called: %s (%d)", player_name, year)

        try:
            player_id: int | None = await asyncio.to_thread(
                resolve_player_id, first_name.strip(), last_name.strip()
            )
            if player_id is None:
                await interaction.followup.send(harry_error(f"No MLBAM ID for {player_name!r}."))
                return

            buf: BytesIO = await asyncio.to_thread(fetch_batter_zone, player_id, year, player_name)

        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /battedzone")
            await interaction.followup.send(harry_error(str(exc)))
            return

        file = discord.File(fp=buf, filename="battedzone.png")
        embed = discord.Embed(
            title=f"🎯 Pitches Received: {player_name}",
            description=(
                f"**Season:** {year}\n**Player ID (MLBAM):** {player_id}\n"
                "All pitches thrown to this batter, colored by pitch type."
            ),
            color=discord.Color.from_rgb(34, 139, 34),
        )
        embed.set_image(url="attachment://battedzone.png")
        embed.set_footer(text="Data: Baseball Savant / Statcast via pybaseball")

        await interaction.followup.send(embed=embed, file=file)
        log.info("/battedzone completed for %s (%d)", player_name, year)
