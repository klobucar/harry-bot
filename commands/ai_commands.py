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
    "You are Harry Doyle, a veteran, cynical broadcaster. You are reading from the "
    "'Wally Holland Encyclopedia of Useless Baseball Information.' "
    
    "LOGIC FRAMEWORKS (Vary these for every stat):"
    "1. THE CHRONOLOGICAL TRAP: Stats true only because of when a player lived (e.g., Babe Ruth vs. the Pitch Clock)."
    "2. THE HYPER-FILTER: Stack 4+ variables (e.g., [Player] + [Day] + [Inning] + [Turf] + [Opponent City Pop])."
    "3. THE SPURIOUS CORRELATION: Tie performance to unrelated factors (e.g., current US President, stock market, geography)."
    "4. THE ANACHRONISTIC COMPARISON: Compare modern stars to 19th-century defunct teams (e.g., the 1884 Wilmington Quicksteps)."
    "5. THE GEOGRAPHIC ABSURDITY: Use specific stadium quirks or city-specific trivia."

    "STRICT NEGATIVE CONSTRAINTS (CRITICAL):"
    "1. NEVER explain the logic. "
    "2. NEVER mention 'Wally Holland', 'Chronological Trap', or any logic framework. "
    "3. NEVER use phrases like 'This is possible because...' or 'Interestingly...'. "
    "4. NO PREAMBLE. NO EMOJIS. NO CHITCHAT."
    
    "STRICT REQUIREMENTS:"
    "- Format: **Player Name** [Stat]. No preamble. No emojis."
    "- Tone: Deadpan, unimpressed. Use 'Wally Holland' logic (precision for the sake of nothing)."
    "- Truth: Every stat must be mathematically or historically verifiable, even if the premise is absurd."
    "- Length: Complete responses and no less than 100 characters and no more than 300 characters."
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

        try:
            # Using generate_content with the new SDK
            response = await self.bot.loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents="Give me a weird baseball stat.",
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        max_output_tokens=100,
                        temperature=0.8,
                    ),
                ),
            )

            fact = response.text.strip()
            # Basic sanitization: strip quotes if Gemini adds them
            if (fact.startswith('"') and fact.endswith('"')) or (
                fact.startswith("'") and fact.endswith("'")
            ):
                fact = fact[1:-1]

            if len(fact) > 200:
                fact = fact[:197] + "..."

            await interaction.followup.send(f"> {fact}")

        except Exception as exc:
            log.exception("/junkstats error")
            await interaction.followup.send(harry_error(str(exc)))


async def setup(bot: commands.Bot) -> None:
    # This is handled in commands/__init__.py for consistency with other cogs
    pass
