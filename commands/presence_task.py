import asyncio
import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks

from mlb_api import fetch_live_scores

log = logging.getLogger("harry")

DEFAULT_ACTIVITY = discord.Game(name="Juuust a bit outside.")

class PresenceTask(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._last_day = None
        self._day_indicators = (False, False)  # (has_checked, is_done)
        self.update_presence.start()

    def cog_unload(self):
        self.update_presence.cancel()

    @tasks.loop(minutes=5)
    async def update_presence(self) -> None:
        """Sophisticated update: only polls when relevant, shows scores during games."""
        if not self.bot.is_ready():
            return

        now = datetime.now(UTC)
        today = now.date()

        # Reset if the calendar flipped
        if self._last_day != today:
            self._last_day = today
            self._day_indicators = (False, False)
            log.info("Presence task: It's a new day (%s). Resetting Tigers watch.", today)

        _has_checked, is_done = self._day_indicators
        if is_done:
            return

        try:
            # We fetch once to get the schedule, then continue fetching if a game is pending or live.
            # If the user says "at most a game a day", we capitalize on that.
            games = await asyncio.to_thread(fetch_live_scores, "DET")
            if not games:
                self._day_indicators = (True, True)
                await self.bot.change_presence(activity=DEFAULT_ACTIVITY)
                return

            # Take the primary game for today
            game = games[0]
            status = game["status"]

            # Logic for update
            if "Final" in status or "Postponed" in status or "Cancelled" in status:
                log.info("Presence task: Game is %s. Done for today.", status)
                self._day_indicators = (True, True)
                await self.bot.change_presence(activity=DEFAULT_ACTIVITY)
                return

            if any(s in status for s in ("In Progress", "Live", "Warmup", "Pre-Game")):
                # Game is happening or close. Show the score!
                # Format: DET 4 @ NYY 2 (Top 8th)
                # Shorten team names if they are standard "Detroit Tigers" -> "DET"
                # Actually, the API gives team names like "Detroit Tigers".
                # We'll use them but keep it concise.
                away = game["away_team"].replace("Detroit Tigers", "Tigers")
                home = game["home_team"].replace("Detroit Tigers", "Tigers")

                msg = f"{away} {game['away_score']} @ {home} {game['home_score']} ({game['inning']})"
                await self.bot.change_presence(activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=msg
                ))
            else:
                # Preview / Scheduled
                start_str = game.get("start_time")
                if start_str:
                    # e.g. "2024-03-28T20:10:00Z"
                    dt = datetime.fromisoformat(start_str)
                    t_str = dt.strftime("%-I:%M %p").lower()
                    msg = f"Tigers @ {t_str} ET" # Typical baseball shorthand
                else:
                    msg = f"Upcoming: {game['away_team']} @ {game['home_team']}"

                await self.bot.change_presence(activity=discord.Game(name=msg))

        except ValueError:
            # fetch_live_scores raises ValueError if no game today
            log.info("Presence task: No Tigers game today. See ya tomorrow.")
            self._day_indicators = (True, True)
            await self.bot.change_presence(activity=DEFAULT_ACTIVITY)
        except Exception:
            log.exception("Error in update_presence task")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PresenceTask(bot))
