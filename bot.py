"""
bot.py — HarryBot: the Discord bot subclass.

Uses commands.Bot (not discord.Client) so that Cog support (add_cog) is
available. commands.Bot owns a CommandTree via self.tree automatically.
"""

from __future__ import annotations

import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from logging_config import current_rss_mb, get_logger
from metrics import COMMAND_DURATION
from persona import harry_error, safe_exc_label

log = logging.getLogger("harry")
log.setLevel(logging.INFO)

# Structured logger for machine-readable events (command.done / command.error).
slog = get_logger("harry")

# Disable overly verbose discord.py debug logs
discord_logger = logging.getLogger("discord")
discord_logger.setLevel(logging.WARNING)

_OWNER_ONLY_DM_MSG = "Juuust a bit outside my jurisdiction, pal. I only take calls from the owner."


def _command_name(
    interaction: discord.Interaction,
    command: app_commands.Command | app_commands.ContextMenu | None = None,
) -> str | None:
    return getattr(command or interaction.command, "qualified_name", None)


def _command_fields(
    interaction: discord.Interaction,
    command: app_commands.Command | app_commands.ContextMenu | None = None,
) -> dict[str, object]:
    """Build the structured fields for a command.done / command.error event.

    `wall_ms` is derived from the `t0` stamped in interaction_check; `rss_mb`
    is best-effort current RSS (omitted off-Linux). Safe to call from any
    command outcome path.
    """
    fields: dict[str, object] = {
        "command": _command_name(interaction, command),
        "user_id": interaction.user.id if interaction.user else None,
        "guild_id": interaction.guild_id,
    }
    t0 = interaction.extras.get("t0")
    if t0 is not None:
        fields["wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    rss = current_rss_mb()
    if rss is not None:
        fields["rss_mb"] = rss
    return fields


def _record_duration(
    interaction: discord.Interaction,
    outcome: str,
    command: app_commands.Command | app_commands.ContextMenu | None = None,
) -> None:
    """Observe the command's wall time in the duration histogram.

    `outcome` is "ok", "error" or "cooldown". A command that catches its own
    exception and replies with an error message still counts as "ok", the
    same as its command.done log line.
    """
    t0 = interaction.extras.get("t0")
    if t0 is None:
        return
    COMMAND_DURATION.labels(
        command=_command_name(interaction, command) or "unknown", outcome=outcome
    ).observe(time.perf_counter() - t0)


class HarryBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # Create a lean Bot without internal caching to fit into a 256MB container.
        # - Slash commands do not require tracking historical server messages.
        # - We don't need to eagerly fetch every member of a massive server on startup.
        super().__init__(
            command_prefix="!",
            intents=intents,
            max_messages=None,
            chunk_guilds_at_startup=False,
            member_cache_flags=discord.MemberCacheFlags.none(),
        )

        raw = os.environ.get("OWNER_ID", "")
        self._owner_id: int | None = int(raw) if raw.strip().isdigit() else None
        if self._owner_id is None:
            log.warning(
                "OWNER_ID is not set — DM access is unrestricted. "
                "Set OWNER_ID=<your Discord user ID> to lock DMs to yourself."
            )

        # Global slash-command check: block non-owner slash commands in DMs.
        # Also the earliest hook before a command body runs, so it's where we
        # stamp the start time used to compute command latency.
        #
        # NOTE: CommandTree.interaction_check is a method invoked as
        # `await self.interaction_check(interaction)` — it must be *assigned*,
        # not used as a decorator. (The old `@self.tree.interaction_check` form
        # silently no-op'd: it called the default check with the function as the
        # interaction arg, leaving the real check as the always-True default.)
        async def _owner_dm_check(interaction: discord.Interaction) -> bool:
            interaction.extras["t0"] = time.perf_counter()
            if (
                self._owner_id is not None
                and isinstance(interaction.channel, discord.DMChannel)
                and interaction.user.id != self._owner_id
            ):
                await interaction.response.send_message(_OWNER_ONLY_DM_MSG, ephemeral=True)
                return False
            return True

        self.tree.interaction_check = _owner_dm_check

        # Global error handler: translate cooldown rejections into Harry's voice.
        # Cooldown fires BEFORE the command body, so interaction.response is
        # still unsent — send_message works here (defer/followup hasn't happened).
        @self.tree.error
        async def _on_app_command_error(
            interaction: discord.Interaction,
            error: app_commands.AppCommandError,
        ) -> None:
            if isinstance(error, app_commands.CommandOnCooldown):
                _record_duration(interaction, "cooldown")
                retry = max(1, int(error.retry_after))
                msg = harry_error(f"Slow down, pal — try again in {retry}s.")
            else:
                _record_duration(interaction, "error")
                # CommandInvokeError wraps the real exception in .original.
                inner = getattr(error, "original", error)
                log.error("Unhandled app command error", exc_info=inner)
                msg = harry_error(safe_exc_label(inner))

            slog.warning(
                "command.error",
                error=type(getattr(error, "original", error)).__name__,
                **_command_fields(interaction),
            )

            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ) -> None:
        """Emit a structured latency event after a slash command succeeds."""
        _record_duration(interaction, "ok", command)
        slog.info("command.done", **_command_fields(interaction, command))

    async def setup_hook(self) -> None:
        from commands import setup

        await setup(self)

        dev_guild_id = os.environ.get("DEV_GUILD_ID")
        if dev_guild_id:
            # Guild sync is instant — use this during development
            guild = discord.Object(id=int(dev_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to dev guild %s (instant).", dev_guild_id)
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
        if self.user is None:
            raise RuntimeError("Bot.user is None on_ready")
        log.info("Harry's in the booth. Logged in as %s (id=%s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening, name="Calling the game. Juuust a bit outside."
            )
        )
