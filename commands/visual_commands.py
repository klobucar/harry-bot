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

from persona import harry_error
from statcast import fetch_spray_chart, resolve_player_id
from utils import validate_statcast_year

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
        year="Season year (e.g. 2023)",
        team_stadium="Stadium to use, e.g. 'tigers', 'yankees', 'generic'",
    )
    async def spraychart(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        year: int,
        team_stadium: str = "generic",
    ) -> None:
        if err := validate_statcast_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        stadium = team_stadium.strip().lower()
        log.info(f"/spraychart called: {player_name} ({year}) @ {stadium}")

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
        log.info(f"/spraychart completed for {player_name} ({year})")
