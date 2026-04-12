"""
commands/advanced_commands.py — Advanced stat commands.

Commands: /hotcold, /exitvelo, /percentile, /career, /leaderboard
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from persona import harry_error
from statcast import (
    aggregate_career_frames,
    fetch_exit_velo,
    fetch_hot_cold,
    fetch_leaderboard,
    fetch_percentile_ranks,
    fetch_player_mlb_years,
    fetch_year_fangraphs,
    resolve_player_id,
)
from utils import current_year, validate_fangraphs_year, validate_statcast_year

log = logging.getLogger("harry")

_PLAYER_TYPE_CHOICES = [
    app_commands.Choice(name="Batter", value="batter"),
    app_commands.Choice(name="Pitcher", value="pitcher"),
]


class AdvancedCommands(commands.Cog):
    """Advanced Statcast and FanGraphs stat commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -----------------------------------------------------------------------
    # /hotcold
    # -----------------------------------------------------------------------
    @app_commands.command(name="hotcold", description="Rolling Statcast stats for the last N days.")
    @app_commands.describe(
        first_name="Player's first name",
        last_name="Player's last name",
        days="Number of days to look back (7, 14, or 30)",
        player_type="Batter or pitcher",
    )
    @app_commands.choices(player_type=_PLAYER_TYPE_CHOICES)
    async def hotcold(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        days: int = 14,
        player_type: str = "batter",
    ) -> None:
        await interaction.response.defer(thinking=True)
        days = max(3, min(days, 60))
        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        log.info("/hotcold: %s last %dd [%s]", player_name, days, player_type)

        try:
            player_id: int | None = await asyncio.to_thread(
                resolve_player_id, first_name.strip(), last_name.strip()
            )
            if player_id is None:
                await interaction.followup.send(harry_error(f"No MLBAM ID for {player_name!r}."))
                return

            stats: dict = await asyncio.to_thread(
                fetch_hot_cold, player_id, days, player_name, player_type
            )
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("/hotcold error")
            await interaction.followup.send(harry_error(str(exc)))
            return

        emoji = "🔥" if player_type == "batter" else "⚾"
        embed = discord.Embed(
            title=f"{emoji} {player_name} — Last {days} Days",
            color=discord.Color.from_rgb(255, 140, 0),
        )
        for k, v in stats.items():
            if k != "period":
                embed.add_field(name=k, value=str(v), inline=True)
        embed.set_footer(text="Data: Baseball Savant / Statcast via pybaseball")
        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /exitvelo
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="exitvelo", description="Batter's exit velocity and barrel stats for a season."
    )
    @app_commands.describe(
        first_name="Batter's first name",
        last_name="Batter's last name",
        year="Season year (2015 or later)",
    )
    async def exitvelo(
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
        log.info("/exitvelo: %s (%d)", player_name, year)

        try:
            player_id: int | None = await asyncio.to_thread(
                resolve_player_id, first_name.strip(), last_name.strip()
            )
            if player_id is None:
                await interaction.followup.send(harry_error(f"No MLBAM ID for {player_name!r}."))
                return

            stats: dict = await asyncio.to_thread(fetch_exit_velo, player_id, year, player_name)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("/exitvelo error")
            await interaction.followup.send(harry_error(str(exc)))
            return

        embed = discord.Embed(
            title=f"💥 Exit Velocity: {player_name} — {year}",
            color=discord.Color.from_rgb(220, 50, 50),
        )
        for k, v in stats.items():
            embed.add_field(name=k, value=str(v), inline=True)
        embed.set_footer(text="Data: Baseball Savant / Statcast via pybaseball")
        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /percentile
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="percentile", description="Statcast percentile ranks for a pitcher or batter."
    )
    @app_commands.describe(
        first_name="Player's first name",
        last_name="Player's last name",
        year="Season year (2015 or later)",
        player_type="Batter or pitcher",
    )
    @app_commands.choices(player_type=_PLAYER_TYPE_CHOICES)
    async def percentile(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        year: int,
        player_type: str = "pitcher",
    ) -> None:
        if err := validate_statcast_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)

        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        log.info("/percentile: %s (%d) [%s]", player_name, year, player_type)

        try:
            player_id: int | None = await asyncio.to_thread(
                resolve_player_id, first_name.strip(), last_name.strip()
            )
            if player_id is None:
                await interaction.followup.send(harry_error(f"No MLBAM ID for {player_name!r}."))
                return

            ranks: dict = await asyncio.to_thread(
                fetch_percentile_ranks, player_id, year, player_name, player_type
            )
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("/percentile error")
            await interaction.followup.send(harry_error(str(exc)))
            return

        embed = discord.Embed(
            title=f"📊 Percentile Ranks: {player_name} — {year}",
            description="*Higher = better vs. league average*",
            color=discord.Color.from_rgb(70, 130, 180),
        )
        for stat, rank in ranks.items():
            embed.add_field(name=stat, value=rank, inline=True)
        embed.set_footer(text="Data: Baseball Savant / Statcast via pybaseball")
        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /career
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="career", description="Career aggregate FanGraphs stats for a player."
    )
    @app_commands.describe(
        first_name="Player's first name",
        last_name="Player's last name",
        last_n_years="Optional: limit to last N seasons (e.g. 3). Default: full career.",
    )
    async def career(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        last_n_years: int | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        cy = current_year()
        log.info("/career: %s", player_name)

        # Lookup debut + last active year — runs in a thread so it doesn't block
        debut, _ = await asyncio.to_thread(
            fetch_player_mlb_years, first_name.strip(), last_name.strip()
        )
        debut = max(debut, 2002)
        years = list(range(debut, cy + 1))

        # If the user asked for fewer seasons, take the tail end
        if last_n_years is not None:
            last_n_years = max(1, last_n_years)
            years = years[-last_n_years:]

        log.info("/career: %s years %d-%d", player_name, years[0], years[-1])

        sem = asyncio.Semaphore(1)

        async def _bounded(yr: int, player_type: str):
            async with sem:
                return player_type, await asyncio.to_thread(
                    fetch_year_fangraphs, yr, player_type, first_name.strip(), last_name.strip()
                )

        tasks = [_bounded(yr, t) for yr in years for t in ("pitcher", "batter")]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            log.exception("/career gather error")
            await interaction.followup.send(harry_error(str(exc)))
            return

        pitch_frames, bat_frames = [], []
        for item in results:
            if isinstance(item, BaseException):
                continue
            player_type, df = item
            if df is not None:
                (pitch_frames if player_type == "pitcher" else bat_frames).append(df)

        try:
            result = aggregate_career_frames(
                pitch_frames, bat_frames, first_name.strip(), last_name.strip(), years
            )
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return

        embed = discord.Embed(
            title=f"🏆 Career Stats: {player_name}",
            description=f"**Type:** {result['type'].title()} | **{result['team']}**",
            color=discord.Color.from_rgb(160, 32, 240),
        )
        for k, v in result["stats"].items():
            embed.add_field(name=k, value=str(v), inline=True)
        embed.set_footer(text="Data: FanGraphs via pybaseball")
        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /leaderboard
    # -----------------------------------------------------------------------
    @app_commands.command(name="leaderboard", description="Top 10 players for any FanGraphs stat.")
    @app_commands.describe(
        stat="Stat column name, e.g. ERA, WAR, HR, K%, OPS, wRC+, FIP",
        year="Season year (2002 or later)",
        player_type="Batter, pitcher, or auto-detect",
    )
    @app_commands.choices(
        player_type=[
            app_commands.Choice(name="Auto-detect", value="auto"),
            app_commands.Choice(name="Batter", value="batter"),
            app_commands.Choice(name="Pitcher", value="pitcher"),
        ]
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        stat: str,
        year: int,
        player_type: str = "auto",
    ) -> None:
        if err := validate_fangraphs_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        log.info("/leaderboard: %s %d [%s]", stat, year, player_type)

        try:
            leaders: list[dict] = await asyncio.to_thread(
                fetch_leaderboard, stat.strip(), year, player_type
            )
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)))
            return
        except Exception as exc:
            log.exception("/leaderboard error")
            await interaction.followup.send(harry_error(str(exc)))
            return

        rows = "\n".join(
            f"{entry['rank']:>2}. {entry['name']:<22} {entry['team']:<5} {entry['value']}"
            for entry in leaders
        )
        embed = discord.Embed(
            title=f"🏅 {stat.upper()} Leaders — {year}",
            description=f"```\n{rows}\n```",
            color=discord.Color.from_rgb(255, 200, 0),
        )
        embed.set_footer(text="Data: FanGraphs via pybaseball")
        await interaction.followup.send(embed=embed)
