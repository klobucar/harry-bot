"""
commands/stats_commands.py — /arsenal, /stats, and /compare slash commands.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from commands.autocomplete import (
    first_name_autocomplete,
    last_name_autocomplete,
    make_first_name_autocomplete,
    make_last_name_autocomplete,
)
from fangraphs import PlayerType, fetch_player_stats, player_role_blocks
from persona import harry_error, safe_exc_label
from statcast import fetch_pitch_arsenal, resolve_player_id
from utils import current_season, validate_fangraphs_year, validate_statcast_year

log = logging.getLogger("harry")


class StatsCommands(commands.Cog):
    """FanGraphs / Statcast stat summary commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -----------------------------------------------------------------------
    # /arsenal
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="arsenal",
        description="Show a pitcher's pitch arsenal — velocity, spin rate, and usage for a season.",
    )
    @app_commands.describe(
        first_name="Pitcher's first name",
        last_name="Pitcher's last name",
        year="Season year (e.g. 2024). Defaults to current season.",
    )
    @app_commands.autocomplete(
        first_name=first_name_autocomplete,
        last_name=last_name_autocomplete,
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def arsenal(
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
        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        await interaction.response.defer(thinking=True)

        try:
            player_id: int | None = await resolve_player_id(first_name.strip(), last_name.strip())
            if player_id is None:
                await interaction.followup.send(
                    harry_error(f"No MLBAM ID for {player_name!r}."), ephemeral=True
                )
                return

            pitches: list[dict] = await fetch_pitch_arsenal(player_id, year)

        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("Unexpected error in /arsenal")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        # Format as a compact code-block table
        header = f"{'Pitch':<12} {'MPH':>6} {'Spin':>6} {'Usage':>7}"
        rows = "\n".join(
            f"{p['pitch']:<12} {p['mph']:>6.1f} {p['spin']:>6.0f} {p['usage']:>6.1f}%"
            for p in pitches
        )
        table = f"```\n{header}\n{'-' * 35}\n{rows}\n```"

        embed = discord.Embed(
            title=f"⚾ Pitch Arsenal: {player_name}",
            description=f"**Season:** {year}\n{table}",
            color=discord.Color.from_rgb(70, 130, 180),  # steel blue
        )
        embed.set_footer(text="Data: Baseball Savant / Statcast via bigleague")

        await interaction.followup.send(embed=embed)
        log.info("/arsenal completed: %s (%d)", player_name, year)

    # -----------------------------------------------------------------------
    # /stats
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="stats",
        description="Show FanGraphs season stats for a pitcher or batter.",
    )
    @app_commands.describe(
        first_name="Player's first name",
        last_name="Player's last name",
        year="Season year (e.g. 2024). Defaults to current season.",
    )
    @app_commands.autocomplete(
        first_name=first_name_autocomplete,
        last_name=last_name_autocomplete,
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def stats(
        self,
        interaction: discord.Interaction,
        first_name: str,
        last_name: str,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        if err := validate_fangraphs_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        player_name = f"{first_name.strip().title()} {last_name.strip().title()}"
        await interaction.response.defer(thinking=True)

        try:
            result: dict = await fetch_player_stats(first_name.strip(), last_name.strip(), year)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("Unexpected error in /stats")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        roles = player_role_blocks(result)
        player_type = result["type"]
        role_summary = " | ".join(
            f"**{role.title()}:** {block.get('team', 'N/A')}" for role, block in roles.items()
        )

        embed = discord.Embed(
            title=f"📊 {player_name} — {year} Stats",
            description=f"**Type:** {player_type.title()} | {role_summary}",
            color=discord.Color.from_rgb(34, 139, 34),
        )
        multiple_roles = len(roles) > 1
        for role, block in roles.items():
            stats = block.get("stats", {})
            if not isinstance(stats, dict):
                continue
            for name, value in stats.items():
                field_name = f"{role.title()} · {name}" if multiple_roles else name
                embed.add_field(name=field_name, value=str(value), inline=True)
        embed.set_footer(text="Data: FanGraphs via bigleague")

        await interaction.followup.send(embed=embed)
        log.info("/stats completed: %s (%d) [%s]", player_name, year, player_type)

    # -----------------------------------------------------------------------
    # /compare
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="compare",
        description="Compare two players' FanGraphs stats side by side.",
    )
    @app_commands.describe(
        p1_first="First player's first name",
        p1_last="First player's last name",
        p2_first="Second player's first name",
        p2_last="Second player's last name",
        year="Season year (e.g. 2024). Defaults to current season.",
    )
    @app_commands.autocomplete(
        p1_first=make_first_name_autocomplete("p1_last"),
        p1_last=make_last_name_autocomplete("p1_first"),
        p2_first=make_first_name_autocomplete("p2_last"),
        p2_last=make_last_name_autocomplete("p2_first"),
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def compare(
        self,
        interaction: discord.Interaction,
        *,
        p1_first: str,
        p1_last: str,
        p2_first: str,
        p2_last: str,
        year: int | None = None,
    ) -> None:
        year = year if year is not None else current_season()
        if err := validate_fangraphs_year(year):
            await interaction.response.send_message(harry_error(err), ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        p1_name = f"{p1_first.strip().title()} {p1_last.strip().title()}"
        p2_name = f"{p2_first.strip().title()} {p2_last.strip().title()}"
        log.info("/compare called: %s vs %s (%d)", p1_name, p2_name, year)

        try:
            p1_result, p2_result = await asyncio.gather(
                fetch_player_stats(p1_first.strip(), p1_last.strip(), year),
                fetch_player_stats(p2_first.strip(), p2_last.strip(), year),
            )
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("Unexpected error in /compare")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        p1_roles = player_role_blocks(p1_result)
        p2_roles = player_role_blocks(p2_result)
        shared_roles: list[PlayerType] = [
            role for role in ("pitcher", "batter") if role in p1_roles and role in p2_roles
        ]
        if not shared_roles:
            await interaction.followup.send(
                harry_error(
                    f"{p1_name} and {p2_name} have no shared FanGraphs role "
                    "(pitcher or batter) to compare."
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"⚖️ {p1_name} vs. {p2_name} — {year}",
            description=f"**Compared role(s):** {', '.join(r.title() for r in shared_roles)}",
            color=discord.Color.from_rgb(160, 32, 240),
        )
        for role in shared_roles:
            p1_stats = p1_roles[role].get("stats", {})
            p2_stats = p2_roles[role].get("stats", {})
            if not isinstance(p1_stats, dict) or not isinstance(p2_stats, dict):
                continue
            all_keys = list(dict.fromkeys([*p1_stats, *p2_stats]))
            for key in all_keys:
                v1 = str(p1_stats.get(key, "—"))
                v2 = str(p2_stats.get(key, "—"))
                field_name = f"{role.title()} · {key}" if len(shared_roles) > 1 else key
                embed.add_field(
                    name=field_name,
                    value=f"{p1_name}: **{v1}**\n{p2_name}: **{v2}**",
                    inline=True,
                )
        embed.set_footer(text="Data: FanGraphs via bigleague")

        await interaction.followup.send(embed=embed)
        log.info("/compare completed: %s vs %s (%d)", p1_name, p2_name, year)
