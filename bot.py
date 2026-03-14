"""
bot.py — HarryBot: the Discord bot subclass.

Uses commands.Bot (not discord.Client) so that Cog support (add_cog) is
available. commands.Bot owns a CommandTree via self.tree automatically.
"""

from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

log = logging.getLogger("harry")


class HarryBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # command_prefix is required by commands.Bot but unused — slash commands only
        super().__init__(command_prefix="!", intents=intents)

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

    async def on_ready(self) -> None:
        assert self.user is not None  # guaranteed once on_ready fires
        log.info(f"Harry's in the booth. Logged in as {self.user} (id={self.user.id})")
        await self.change_presence(
            activity=discord.Game(name="/strikezone | /matchup — Juuust a bit outside.")
        )
