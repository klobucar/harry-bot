"""
commands/matchup_commands.py — /matchup and /matchupzone slash commands.
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

from commands.autocomplete import (
    make_first_name_autocomplete,
    make_last_name_autocomplete,
)
from persona import harry_error, safe_exc_label
from statcast import compute_matchup_stats, fetch_matchup_zone, resolve_player_id
from utils import current_season, validate_statcast_year

_pitcher_first_ac = make_first_name_autocomplete("pitcher_last")
_pitcher_last_ac = make_last_name_autocomplete("pitcher_first")
_batter_first_ac = make_first_name_autocomplete("batter_last")
_batter_last_ac = make_last_name_autocomplete("batter_first")

log = logging.getLogger("harry")


class MatchupCommands(commands.Cog):
    """Head-to-head pitcher vs. batter commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -----------------------------------------------------------------------
    # Shared helper: resolve pitcher + batter IDs concurrently
    # -----------------------------------------------------------------------
    async def _resolve_both(
        self,
        interaction: discord.Interaction,
        pitcher_first: str,
        pitcher_last: str,
        batter_first: str,
        batter_last: str,
        pitcher_name: str,
        batter_name: str,
    ) -> tuple[int, int] | None:
        """
        Resolve both player IDs concurrently.
        Sends an error followup and returns None if either lookup fails.
        """
        pitcher_id_task = asyncio.to_thread(resolve_player_id, pitcher_first, pitcher_last)
        batter_id_task = asyncio.to_thread(resolve_player_id, batter_first, batter_last)
        pitcher_id, batter_id = await asyncio.gather(pitcher_id_task, batter_id_task)

        if pitcher_id is None:
            await interaction.followup.send(
                harry_error(f"No MLBAM ID for pitcher {pitcher_name!r}.")
            )
            return None
        if batter_id is None:
            await interaction.followup.send(harry_error(f"No MLBAM ID for batter {batter_name!r}."))
            return None

        return pitcher_id, batter_id

    # -----------------------------------------------------------------------
    # /matchup
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="matchup",
        description="Head-to-head batting stats between a pitcher and batter for a season.",
    )
    @app_commands.describe(
        pitcher_first="Pitcher's first name",
        pitcher_last="Pitcher's last name",
        batter_first="Batter's first name",
        batter_last="Batter's last name",
        year="Season year (e.g. 2024). Defaults to current season.",
    )
    @app_commands.autocomplete(
        pitcher_first=_pitcher_first_ac,
        pitcher_last=_pitcher_last_ac,
        batter_first=_batter_first_ac,
        batter_last=_batter_last_ac,
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def matchup(
        self,
        interaction: discord.Interaction,
        pitcher_first: str,
        pitcher_last: str,
        batter_first: str,
        batter_last: str,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        if err := validate_statcast_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        pitcher_name = f"{pitcher_first.strip().title()} {pitcher_last.strip().title()}"
        batter_name = f"{batter_first.strip().title()} {batter_last.strip().title()}"
        log.info("/matchup: %s vs %s (%d)", pitcher_name, batter_name, year)

        try:
            ids = await self._resolve_both(
                interaction,
                pitcher_first.strip(),
                pitcher_last.strip(),
                batter_first.strip(),
                batter_last.strip(),
                pitcher_name,
                batter_name,
            )
            if ids is None:
                return
            pitcher_id, batter_id = ids

            stats: dict[str, int | float] = await asyncio.to_thread(
                compute_matchup_stats, pitcher_id, batter_id, year
            )

        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /matchup")
            await interaction.followup.send(harry_error(safe_exc_label(exc)))
            return

        avg_display = f".{round(stats['batting_avg'] * 1000):03d}"

        embed = discord.Embed(
            title=f"⚾ Head-to-Head: {batter_name} vs. {pitcher_name}",
            description=f"**Season:** {year}",
            color=discord.Color.from_rgb(200, 16, 46),
        )
        embed.add_field(name="Plate Appearances", value=str(stats["pa"]), inline=True)
        embed.add_field(name="At-Bats", value=str(stats["ab"]), inline=True)
        embed.add_field(name="Hits", value=str(stats["hits"]), inline=True)
        embed.add_field(name="Batting Average", value=avg_display, inline=True)
        embed.add_field(name="Strikeouts", value=str(stats["strikeouts"]), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.set_footer(
            text=f"Pitcher MLBAM: {pitcher_id} | Batter MLBAM: {batter_id} | Data: Baseball Savant"
        )

        await interaction.followup.send(embed=embed)
        log.info("/matchup completed: %s vs %s (%d)", pitcher_name, batter_name, year)

    # -----------------------------------------------------------------------
    # /matchupzone
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="matchupzone",
        description="Plot the strike zone for a specific pitcher vs. batter matchup.",
    )
    @app_commands.describe(
        pitcher_first="Pitcher's first name",
        pitcher_last="Pitcher's last name",
        batter_first="Batter's first name",
        batter_last="Batter's last name",
        year="Season year (e.g. 2024). Defaults to current season.",
    )
    @app_commands.autocomplete(
        pitcher_first=_pitcher_first_ac,
        pitcher_last=_pitcher_last_ac,
        batter_first=_batter_first_ac,
        batter_last=_batter_last_ac,
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def matchupzone(
        self,
        interaction: discord.Interaction,
        pitcher_first: str,
        pitcher_last: str,
        batter_first: str,
        batter_last: str,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        if err := validate_statcast_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        pitcher_name = f"{pitcher_first.strip().title()} {pitcher_last.strip().title()}"
        batter_name = f"{batter_first.strip().title()} {batter_last.strip().title()}"
        log.info("/matchupzone: %s vs %s (%d)", pitcher_name, batter_name, year)

        try:
            ids = await self._resolve_both(
                interaction,
                pitcher_first.strip(),
                pitcher_last.strip(),
                batter_first.strip(),
                batter_last.strip(),
                pitcher_name,
                batter_name,
            )
            if ids is None:
                return
            pitcher_id, batter_id = ids

            buf: BytesIO = await asyncio.to_thread(
                fetch_matchup_zone, pitcher_id, batter_id, year, pitcher_name, batter_name
            )

        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("Unexpected error in /matchupzone")
            await interaction.followup.send(harry_error(safe_exc_label(exc)))
            return

        file = discord.File(fp=buf, filename="matchupzone.png")
        embed = discord.Embed(
            title=f"⚔️ Matchup Zone: {batter_name} vs. {pitcher_name}",
            description=(
                f"**Season:** {year}\n"
                "Every pitch this pitcher threw to this batter, colored by pitch type."
            ),
            color=discord.Color.from_rgb(160, 32, 240),
        )
        embed.set_image(url="attachment://matchupzone.png")
        embed.set_footer(
            text=f"Pitcher MLBAM: {pitcher_id} | Batter MLBAM: {batter_id} | Data: Baseball Savant"
        )

        await interaction.followup.send(embed=embed, file=file)
        log.info("/matchupzone completed: %s vs %s (%d)", pitcher_name, batter_name, year)
