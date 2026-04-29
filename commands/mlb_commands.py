"""
commands/mlb_commands.py — Live MLB data commands via the official MLB Stats API.

Commands: /roster, /injury, /transactions, /livescore, /nextgame
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from mlb_api import (
    fetch_injuries,
    fetch_live_scores,
    fetch_next_game,
    fetch_roster,
    fetch_transactions,
)
from persona import harry_error, safe_exc_label

log = logging.getLogger("harry")

_TEAM_HINT = "Team abbreviation, e.g. DET, CLE, NYY, LAD"


class MLBCommands(commands.Cog):
    """Live MLB data — roster, injuries, transactions, scores."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -----------------------------------------------------------------------
    # /roster
    # -----------------------------------------------------------------------
    @app_commands.command(name="roster", description="Show a team's current active 26-man roster.")
    @app_commands.describe(team=_TEAM_HINT)
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def roster(self, interaction: discord.Interaction, team: str) -> None:
        await interaction.response.defer(thinking=True)
        team_up = team.strip().upper()
        log.info("/roster: %s", team_up)

        try:
            players: list[dict] = await asyncio.to_thread(fetch_roster, team_up)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("/roster error")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        # Group by position type
        pitchers = [p for p in players if p["pos"] in ("SP", "RP", "P")]
        position = [p for p in players if p["pos"] not in ("SP", "RP", "P")]

        def _block(group: list[dict]) -> str:
            return "\n".join(
                f"{p['pos']:<4} {p['name']}" for p in sorted(group, key=lambda x: x["pos"])
            )

        embed = discord.Embed(
            title=f"📋 {team_up} Active Roster",
            color=discord.Color.from_rgb(0, 40, 104),
        )
        if pitchers:
            embed.add_field(name="Pitchers", value=f"```\n{_block(pitchers)}\n```", inline=False)
        if position:
            embed.add_field(
                name="Position Players", value=f"```\n{_block(position)}\n```", inline=False
            )
        embed.set_footer(text="Data: MLB Stats API")

        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /injury
    # -----------------------------------------------------------------------
    @app_commands.command(name="injury", description="Show a team's current IL stints.")
    @app_commands.describe(team=_TEAM_HINT)
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def injury(self, interaction: discord.Interaction, team: str) -> None:
        await interaction.response.defer(thinking=True)
        team_up = team.strip().upper()
        log.info("/injury: %s", team_up)

        try:
            players: list[dict] = await asyncio.to_thread(fetch_injuries, team_up)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("/injury error")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        if not players:
            await interaction.followup.send(f"✅ {team_up} has no players on the IL right now.")
            return

        rows = "\n".join(f"{p['pos']:<4} {p['name']:<22} {p['note']}" for p in players)
        embed = discord.Embed(
            title=f"🩹 {team_up} Injured List",
            description=f"```\n{rows}\n```",
            color=discord.Color.from_rgb(220, 50, 50),
        )
        embed.set_footer(text="Data: MLB Stats API")
        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /transactions
    # -----------------------------------------------------------------------
    @app_commands.command(name="transactions", description="Show recent roster moves for a team.")
    @app_commands.describe(team=_TEAM_HINT, days="How many days back to look (default 7)")
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def transactions(
        self,
        interaction: discord.Interaction,
        team: str,
        days: int = 7,
    ) -> None:
        await interaction.response.defer(thinking=True)
        team_up = team.strip().upper()
        days = max(1, min(days, 30))
        log.info("/transactions: %s last %dd", team_up, days)

        try:
            moves: list[dict] = await asyncio.to_thread(fetch_transactions, team_up, days)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("/transactions error")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        lines = [f"{m['date']}  {m['desc']}" for m in moves[:15]]
        embed = discord.Embed(
            title=f"📰 {team_up} Transactions — Last {days} Days",
            description="```\n" + "\n".join(lines) + "\n```",
            color=discord.Color.from_rgb(70, 130, 180),
        )
        embed.set_footer(text="Data: MLB Stats API")
        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /livescore
    # -----------------------------------------------------------------------
    @app_commands.command(name="livescore", description="Get today's live score for a team.")
    @app_commands.describe(team=_TEAM_HINT)
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def livescore(self, interaction: discord.Interaction, team: str) -> None:
        await interaction.response.defer(thinking=True)
        team_up = team.strip().upper()
        log.info("/livescore: %s", team_up)

        try:
            games: list[dict] = await asyncio.to_thread(fetch_live_scores, team_up)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("/livescore error")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        embed = discord.Embed(
            title=f"⚾ Live Score — {team_up}",
            color=discord.Color.from_rgb(34, 139, 34),
        )
        for g in games:
            score_line = f"{g['away_team']} {g['away_score']} @ {g['home_team']} {g['home_score']}"
            status_line = f"{g['inning']}" + (
                f" | {g['outs']} out(s)" if g["outs"] is not None else ""
            )
            embed.add_field(name=score_line, value=status_line, inline=False)
        embed.set_footer(text="Data: MLB Stats API")
        await interaction.followup.send(embed=embed)

    # -----------------------------------------------------------------------
    # /nextgame
    # -----------------------------------------------------------------------
    @app_commands.command(
        name="nextgame", description="Show a team's next scheduled game and probable pitchers."
    )
    @app_commands.describe(team=_TEAM_HINT)
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def nextgame(self, interaction: discord.Interaction, team: str) -> None:
        await interaction.response.defer(thinking=True)
        team_up = team.strip().upper()
        log.info("/nextgame: %s", team_up)

        try:
            game: dict = await asyncio.to_thread(fetch_next_game, team_up)
        except ValueError as exc:
            await interaction.followup.send(harry_error(str(exc)), ephemeral=True)
            return
        except Exception as exc:
            log.exception("/nextgame error")
            await interaction.followup.send(harry_error(safe_exc_label(exc)), ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📅 Next Game: {game['away_team']} @ {game['home_team']}",
            description=f"**Date:** {game['date']}  |  **Time:** {game['time']}",
            color=discord.Color.from_rgb(255, 140, 0),
        )
        embed.add_field(name=f"{game['away_team']} SP", value=game["away_probable"], inline=True)
        embed.add_field(name=f"{game['home_team']} SP", value=game["home_probable"], inline=True)
        embed.set_footer(text="Data: MLB Stats API")
        await interaction.followup.send(embed=embed)
