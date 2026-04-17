"""
commands/__init__.py — registers all Cogs onto the bot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import HarryBot


async def setup(bot: HarryBot) -> None:
    """Add all command Cogs to the bot. Called from HarryBot.setup_hook()."""
    # Deferred imports avoid circular dependency: each commands module imports
    # HarryBot from bot.py, which would create a circular top-level import.
    from commands.advanced_commands import AdvancedCommands
    from commands.ai_commands import AICommands
    from commands.info_commands import InfoCommands
    from commands.matchup_commands import MatchupCommands
    from commands.meta_commands import MetaCommands
    from commands.mlb_commands import MLBCommands
    from commands.presence_task import PresenceTask
    from commands.stats_commands import StatsCommands
    from commands.visual_commands import VisualCommands
    from commands.zone_commands import ZoneCommands

    await bot.add_cog(ZoneCommands(bot))
    await bot.add_cog(MatchupCommands(bot))
    await bot.add_cog(VisualCommands(bot))
    await bot.add_cog(StatsCommands(bot))
    await bot.add_cog(InfoCommands(bot))
    await bot.add_cog(MLBCommands(bot))
    await bot.add_cog(AdvancedCommands(bot))
    await bot.add_cog(AICommands(bot))
    await bot.add_cog(MetaCommands(bot))
    await bot.add_cog(PresenceTask(bot))
