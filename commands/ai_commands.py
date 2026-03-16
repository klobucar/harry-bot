"""
commands/ai_commands.py — Gemini-powered baseball facts.

Commands: /junkstats
"""

from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types

from persona import harry_error

log = logging.getLogger("harry")

SYSTEM_INSTRUCTION = (
    "You are Harry Doyle, the cynical voice of baseball. You are reading from the "
    "'Wally Holland Almanac of Meaningless Precision.' "

    "### THE GOAL\n"
    "Generate one technically true, absurdly specific, and mundane MLB stat. "
    "To do this, you MUST stack at least 2 layers of filters. "

    "### FILTER TOOLKIT (Pick 2+ to stack for every stat and more is great):\n"
    "- HANDEDNESS: Left/Right handed batter or pitcher, switch hitter.\n"
    "- POSITION: Catcher, first base, second base, third base, shortstop, left field, center field, right field, pitcher, designated hitter.\n"
    "- OUTCOME: Wins, losses, saves, holds, blown saves, walks, hits, home runs, runs, RBIs, etc.\n"
    "- CALENDAR: Specific day of the week, half of the season, or month.\n"
    "- ARCHITECTURE: Dome stadiums, retractable roofs, grass vs. turf, or brick backstops.\n"
    "- GEOGRAPHY: ZIP codes, distance from landmarks, or city population.\n"
    "- TECHNOLOGY/MUNDANE: Distance from a post office, presence of WiFi, local transit access, east of the mississippi, etc.\n"
    "- DEFUNCT COMPARISON: Modern player vs. a team from the 1800s (e.g., 1899 Spiders, 1884 Quicksteps).\n"

    "### THE CONSTRAINTS:\n"
    "- NO ZERO STATS: Don't tell me what didn't happen. Tell me a weird total that DID happen.\n"
    "- ONE COMPLETE SENTENCE: Deadpan delivery. No preamble, no 'because', no explanation.\n"
    "- STOP IMMEDIATELY: Finish the sentence and shut up. Do not yap.\n"
    "- FORMAT: **Player or Team Name** [Stat sentence]."
)

class AICommands(commands.Cog):
    """Gemini-powered baseball insights."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            log.warning("GEMINI_API_KEY not found in environment. /junkstats will fail.")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)

    @app_commands.command(
        name="junkstats",
        description="Get an absurdly specific and weird baseball fact from Gemini.",
    )
    async def junkstats(self, interaction: discord.Interaction) -> None:
        if not self.client:
            await interaction.response.send_message(
                harry_error("Gemini API key is missing. Tell the owner to set GEMINI_API_KEY."),
                ephemeral=True,
            )
            return

        client = self.client
        await interaction.response.defer(thinking=True)
        log.info("/junkstats request")

        import random

        # All the eras to keep the bot's brain moving
        eras = [
            "the Pioneer Era", "the Deadball Era", "the Golden Age", 
            "the Baby Boomer Era", "the Artificial Turf Era", 
            "the Free Agency Era", "the Steroid Era", "the Statcast Era"
        ]

        try:
            # Using generate_content with the new SDK
            response = await self.bot.loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model="gemini-3.1-flash-lite-preview",
                    contents=f"Give me a strange and mundane baseball stat from {random.choice(eras)}",
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        max_output_tokens=95, # Tightening this prevents the "explanation" from fitting
                        temperature=0.85,
                        top_p=0.95,
                    ),
                ),
            )

            fact = response.text.strip()
            # Basic sanitization: strip quotes if Gemini adds them
            if (fact.startswith('"') and fact.endswith('"')) or (
                fact.startswith("'") and fact.endswith("'")
            ):
                fact = fact[1:-1]

            await interaction.followup.send(f"> {fact}")

        except Exception as exc:
            log.exception("/junkstats error")
            # Swallow technical details for Gemini/API errors to keep Harry in character.
            from google.genai import errors
            if isinstance(exc, errors.ClientError):
                await interaction.followup.send(harry_error())
            else:
                await interaction.followup.send(harry_error(str(exc)))


async def setup(bot: commands.Bot) -> None:
    # This is handled in commands/__init__.py for consistency with other cogs
    pass
