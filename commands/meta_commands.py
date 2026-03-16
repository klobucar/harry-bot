"""
commands/meta_commands.py — /help command with Harry Doyle flair.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("harry")

_DOYLE_HELP_INTRO = (
    "\"Welcome to the booth, pal. I'm Harry Doyle and I've got all the stats you "
    "didn't know you needed. Here's what I can do — try to keep up.\""
)

_COMMANDS = [
    (
        "📊 **Statcast Plots**",
        [
            (
                "`/strikezone [first] [last] [year]`",
                "Pitcher's strike zone — where the ball crossed the plate",
            ),
            ("`/battedzone [first] [last] [year]`", "All pitches thrown *to* a batter in a season"),
            (
                "`/spraychart [first] [last] [year] (stadium)`",
                "Where a batter hits the ball on a stadium",
            ),
            (
                "`/hotzones [first] [last] [year]`",
                "3x3 thermal grid of a batter's BA in the zone",
            ),
            (
                "`/matchupzone [p_first] [p_last] [b_first] [b_last] [year]`",
                "Zone plot of one pitcher vs one batter",
            ),
            ("`/stadium [team]`", "Ballpark name, location, and visual outline"),
        ],
    ),
    (
        "📈 **Stats**",
        [
            (
                "`/stats [first] [last] [year]`",
                "FanGraphs season stats — auto-detects pitcher or batter",
            ),
            ("`/career [first] [last]`", "Career aggregate stats from FanGraphs"),
            ("`/compare [p1] [p2] [year]`", "Side-by-side stat comparison of two players"),
            ("`/arsenal [first] [last] [year]`", "Pitcher's pitch mix — velocity, spin, usage"),
            ("`/exitvelo [first] [last] [year]`", "Batter's exit velocity and barrel stats"),
            ("`/percentile [first] [last] [year]`", "Pitcher or batter Statcast percentile ranks"),
            (
                "`/hotcold [first] [last] [days] (pitcher/batter)`",
                "Rolling stats for the last N days",
            ),
            (
                "`/leaderboard [stat] [year] (pitcher/batter)`",
                "Top 10 players for any FanGraphs stat",
            ),
            ("`/junkstats`", "Absurdly specific and weird baseball facts from Gemini"),
        ],
    ),
    (
        "⚔️ **Head-to-Head**",
        [
            (
                "`/matchup [p_first] [p_last] [b_first] [b_last] [year]`",
                "H2H text stats: AVG, H, PA, K",
            ),
        ],
    ),
    (
        "🏆 **League Info**",
        [
            ("`/standings [year]`", "All 6 division standings"),
            ("`/schedule [team] [year]`", "Last 5 results + next 5 games"),
            ("`/livescore [team]`", "Today's live score"),
            ("`/nextgame [team]`", "Next scheduled game and probable pitchers"),
            ("`/roster [team]`", "Current active 26-man roster"),
            ("`/injury [team]`", "Current IL stints"),
            ("`/transactions [team] (days)`", "Recent roster moves (default last 7 days)"),
        ],
    ),
]


class MetaCommands(commands.Cog):
    """Meta commands — help and bot info."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="List all Harry's commands.")
    async def help(self, interaction: discord.Interaction) -> None:
        log.info(f"/help called by {interaction.user}")

        embed = discord.Embed(
            title="📻 Harry Doyle — Command Guide",
            description=_DOYLE_HELP_INTRO,
            color=discord.Color.from_rgb(200, 16, 46),
        )

        for section_title, cmds in _COMMANDS:
            value = "\n".join(f"{cmd} — {desc}" for cmd, desc in cmds)
            embed.add_field(name=section_title, value=value, inline=False)

        embed.add_field(
            name="📅 Year limits",
            value=(
                "Statcast commands require **2015 or later**.\n"
                "FanGraphs commands require **2002 or later**."
            ),
            inline=False,
        )
        embed.set_footer(text="Data: Baseball Savant · FanGraphs · MLB Stats API · pybaseball")

        await interaction.response.send_message(embed=embed, ephemeral=True)
