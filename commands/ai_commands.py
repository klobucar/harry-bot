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
    "You are a baseball historian with access to deep sabermetric databases. "
    "Your goal is to provide 'absurdly specific' and 'weird' MLB stats that sound like they shouldn't be a category, but are. "
    "Focus on 'Nested Conditions' to find these stats. "
    "Requirements: "
    "1. Format: A single, punchy sentence. Use **bolding** for the player name and the key stat. "
    "2. Layers of Specificity: Every fact must combine 3+ variables (e.g., Player + Geography + Stadium Type + Weather/Time). "
    "3. Variety: Avoid just home runs. Include weird splits for: pop-outs to specific fielders, performance on birthdays, turf vs. grass differentials, or stats in specific cities they never played for. "
    "4. Truth: It must be a verifiable MLB fact. "
    "5. Length: Under 200 characters for Discord scannability. "
    "Example Style: '**Corey Seager** has the highest career OPS of any active player in retractable-roof stadiums west of the Mississippi.' "
    "Example Style: 'On his 29th birthday, **Mike Trout** hit his 300th career home run, the same day **Joe Sullivan** did it 100 years prior.' "
    "NO PREAMBLE. Just the stat."
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
