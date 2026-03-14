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
    from commands.advanced_commands import AdvancedCommands  # noqa: PLC0415
    from commands.info_commands import InfoCommands  # noqa: PLC0415
    from commands.matchup_commands import MatchupCommands  # noqa: PLC0415
    from commands.meta_commands import MetaCommands  # noqa: PLC0415
    from commands.mlb_commands import MLBCommands  # noqa: PLC0415
    from commands.stats_commands import StatsCommands  # noqa: PLC0415
    from commands.visual_commands import VisualCommands  # noqa: PLC0415
    from commands.zone_commands import ZoneCommands  # noqa: PLC0415

    await bot.add_cog(ZoneCommands(bot))
    await bot.add_cog(MatchupCommands(bot))
    await bot.add_cog(VisualCommands(bot))
    await bot.add_cog(StatsCommands(bot))
    await bot.add_cog(InfoCommands(bot))
    await bot.add_cog(MLBCommands(bot))
    await bot.add_cog(AdvancedCommands(bot))
    await bot.add_cog(MetaCommands(bot))
