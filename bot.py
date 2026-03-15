"""
bot.py — HarryBot: the Discord bot subclass.

Uses commands.Bot (not discord.Client) so that Cog support (add_cog) is
available. commands.Bot owns a CommandTree via self.tree automatically.
"""

from __future__ import annotations

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("harry")
log.setLevel(logging.INFO)

# Disable overly verbose discord.py debug logs
discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.WARNING)

_OWNER_ONLY_DM_MSG = (
    "Juuust a bit outside my jurisdiction, pal. "
    "I only take calls from the owner."
)


class HarryBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # command_prefix is required by commands.Bot but unused — slash commands only
        super().__init__(command_prefix="!", intents=intents)

        raw = os.environ.get("OWNER_ID", "")
        self._owner_id: int | None = int(raw) if raw.strip().isdigit() else None
        if self._owner_id is None:
            log.warning(
                "OWNER_ID is not set — DM access is unrestricted. "
                "Set OWNER_ID=<your Discord user ID> to lock DMs to yourself."
            )

        # Global slash-command check: block non-owner slash commands in DMs.
        @self.tree.interaction_check
        async def _owner_dm_check(interaction: discord.Interaction) -> bool:
            if (
                self._owner_id is not None
                and isinstance(interaction.channel, discord.DMChannel)
                and interaction.user.id != self._owner_id
            ):
                await interaction.response.send_message(
                    _OWNER_ONLY_DM_MSG, ephemeral=True
                )
                return False
            return True

    async def setup_hook(self) -> None:
        from commands import setup  # noqa: PLC0415  (deferred to avoid circular import)

        await setup(self)

        dev_guild_id = os.environ.get("DEV_GUILD_ID")
        if dev_guild_id:
            # Guild sync is instant — use this during development
            guild = discord.Object(id=int(dev_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Slash commands synced to dev guild {dev_guild_id} (instant).")
        else:
            # Global sync — takes up to 1 hour to propagate
            await self.tree.sync()
            log.info("Slash commands synced globally (may take up to 1 hour).")

    async def on_message(self, message: discord.Message) -> None:
        """Drop DMs from anyone who isn't the owner before processing."""
        if (
            self._owner_id is not None
            and isinstance(message.channel, discord.DMChannel)
            and message.author.id != self._owner_id
        ):
            return  # silently ignore
        await super().on_message(message)

    async def on_ready(self) -> None:
        assert self.user is not None  # guaranteed once on_ready fires
        log.info(f"Harry's in the booth. Logged in as {self.user} (id={self.user.id})")
        await self.change_presence(
            activity=discord.Game(name="/strikezone | /matchup — Juuust a bit outside.")
        )
