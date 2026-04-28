"""
commands/ai_commands.py — Gemini-powered baseball facts.

Commands: /junkstats
"""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
from google import genai
from google.genai import types

from persona import harry_error, safe_exc_label

log = logging.getLogger("harry")

SYSTEM_INSTRUCTION = (
    "You are Harry Doyle, the cynical voice of baseball. You are reading from the "
    "'Wally Holland Almanac of Meaningless Precision.'\n"
    "### THE GOAL\n"
    "Generate one technically true, absurdly specific, and mundane MLB stat. "
    "To do this, you MUST stack at least 2 layers of filters. "
    "You may use more if you want. Criteria can be also 3rd best, tied for 2nd best, A specific number for the stat, etc.\n"
    "### THE SUBJECTS\n"
    "Generate a stat about an MLB PLAYER or an MLB TEAM. Switch between them.\n"
    "### THE ERA DICTIONARY:\n"
    "1. PIONEER ERA (1871-1900): High errors, defunct teams (e.g., 1899 Spiders, 1884 Quicksteps).\n"
    "2. DEADBALL ERA (1901-1919): Small-ball, low scoring. Ty Cobb and the Boston Beaneaters.\n"
    "3. GOLDEN AGE (1920-1946): Babe Ruth, the 1927 Yankees, and the rise of the radio.\n"
    "4. INTEGRATION/BABY BOOMERS (1947-1960): The 'Boys of Summer' Dodgers and the classic Giants.\n"
    "5. TURF & TENSION (1961-1979): The 1962 Mets, polyester uniforms, and cookie-cutter stadiums.\n"
    "6. FREE AGENCY & EXPANSION (1980-1993): The 'Whitey Herzog' Cardinals and 1980s Rickey Henderson.\n"
    "7. STEROID ERA (1994-2005): The 2001 Mariners, offensive explosions, and the Bash Brothers.\n"
    "8. STATCAST/MODERN (2015-Present): The Dodgers' payroll, pitch clocks, and Shohei Ohtani.\n"
    "### METRIC MENU (Choose one at random for every stat):\n"
    "- PITCHING: Innings Pitched (IP), ERA, Strikeouts (K), WHIP, Saves, Holds, Wild Pitches.\n"
    "- ADVANCED: WAR (Wins Above Replacement), OPS+, FIP, Range Factor, Win Shares.\n"
    "- BATTING: Doubles, Triples, Intentional Walks, Bunts, Sacrifice Flies, Strikeouts.\n"
    "- MARGINS: Wins by exactly X runs, 1-run losses, extra-inning games played.\n"
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
        description="Get an absurdly specific and weird baseball fact from Harry Doyle.",
    )
    @app_commands.checks.cooldown(3, 30.0, key=lambda i: i.user.id)
    async def junkstats(self, interaction: discord.Interaction) -> None:
        if not self.client:
            await interaction.response.send_message(
                harry_error("Gemini API key is missing. Tell the owner to stop being so cheap!"),
                ephemeral=True,
            )
            return

        client = self.client
        await interaction.response.defer(thinking=True)
        log.info("/junkstats request")

        import random

        # All the eras to keep the bot's brain moving
        eras = [
            "the Pioneer Era",
            "the Deadball Era",
            "the Golden Age",
            "the Baby Boomer Era",
            "the Artificial Turf Era",
            "the Free Agency Era",
            "the Steroid Era",
            "the Statcast Era",
        ]

        metrics = [
            # --- THE MUNDANE & LOGISTICAL ---
            "Bus travel miles logged",
            "Post-season plate appearances",
            "Spring Training wild pitches",
            "Games played while the price of gas was low",
            "Ejections by a home plate umpire",
            "Games played in ZIP codes starting with an even number",
            "Distance from the nearest Post Office",
            "Elevation above sea level",
            "Proximity to a federally funded bridge",
            "Local subway access",
            # --- PITCHING & COMMAND ---
            "Innings Pitched (IP)",
            "Balks",
            "Wild Pitches",
            "Pickoff Attempts",
            "Successful Pickoffs",
            "Hit Batsmen (HBP)",
            "Uncaught Third Strikes",
            "Pitch Clock Violations",
            "Mound Visits",
            "Holds",
            "Blown Saves",
            "Inherited Runners Stranded",
            "Complete Games",
            "Shutouts",
            "Earned Runs allowed on Tuesdays",
            "Intentional Walks issued",
            "Warm-up pitches thrown",
            # --- BATTING & BASERUNNING ---
            "Intentional Walks drawn",
            "Caught Stealing",
            "Stolen Base Percentage on Turf",
            "Sacrifice Bunts",
            "Sacrifice Flies",
            "Infield Singles",
            "Bunt Hits",
            "Grounded into Double Plays (GIDP)",
            "Strikeouts on a Full Count",
            "Pinch-Hit Plate Appearances",
            "Triples west of the Mississippi",
            "Home Runs hit in Dome Stadiums",
            "RBIs on a Friday",
            "Total Bases in Doubleheaders",
            "Lead-off walks",
            "Plate appearances ending in a foul-out",
            # --- DEFENSE & FIELDING ---
            "Range Factor",
            "Defensive Runs Saved (DRS)",
            "Total Zone Runs",
            "Putouts at Shortstop",
            "Assists by a Left-fielder",
            "Errors committed on artificial turf",
            "Double Plays Turned",
            "Outfield Assists",
            "Passed Balls",
            "Catcher's Interference",
            "Putouts at Third Base",
            "Errors in day games",
            "Putouts in extra innings",
            "Infield Fly Rule calls",
            # --- ADVANCED & SABERMETRIC ---
            "WAR (Wins Above Replacement)",
            "OPS+",
            "ERA+",
            "Win Shares",
            "FIP (Fielder Independent Pitching)",
            "Win Probability Added (WPA)",
            "Secondary Average",
            "Isolated Power (ISO)",
            "Batting Average on Balls in Play (BABIP)",
            "Exit Velocity on groundouts",
            # --- TEAM, LEAGUE & MARGINS ---
            "Wins by exactly x run",
            "Losses by exactly x runs",
            "Extra-inning losses",
            "Interleague wins on a Tuesday",
            "Division-lead days",
            "Games behind the leader",
            "Doubleheaders swept",
            "Series sweeps in April",
            "Wins against left-handed starters",
            "One-run victories in dome stadiums",
            "Winning streaks during the second half",
            # --- TRUELY OBSCURE ---
            "Ground ball-to-fly ball ratio (GB/FB)",
            "Opponent Batting Average on a 3-1 count",
            "Average distance of fly-ball outs",
            "Infield fly rule call frequency",
            "Pitcher assists on ground balls to the first base side",
            "Pickoff attempts on runners with lead-off walks",
            "Games played while the Dow Jones finished lower than its opening",
            "Total bases on hits to the opposite field",
            "Errors committed while the sun was at a specific angle (5:00 PM starts)",
            "Successful bunts against southpaws",
            "Wins by exactly seven runs",
            "Extra-inning walks allowed by a closer",
            "Total bases recorded in cities with a name containing the letter 'Z'",
            "Distance from the stadium to the nearest state line",
            "Days spent on the 'Restricted List' due to logistical travel errors",
        ]

        selected_metric = random.choice(metrics)  # noqa: S311
        selected_era = random.choice(eras)  # noqa: S311
        selected_subject = random.choice(["player", "team"])  # noqa: S311

        try:
            # Using the Async Client (aio) with a 15s timeout.
            # This allows true cancellation of the network request if timed out.
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model="gemini-3.1-flash-lite-preview",
                    contents=(
                        f"Use the metric '{selected_metric}' as inspiration to find a convoluted, "
                        f"mundane, and technically true stat about a {selected_subject} from {selected_era}. "
                        f"Avoid common totals; look for weird, specific numbers."
                        f"The goal is correlation with zero causation."
                        f"Make the format look like a statcast stat and flow naturally."
                    ),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        max_output_tokens=110,  # Tightening this prevents the "explanation" from fitting
                        temperature=0.90,
                        top_p=0.95,
                    ),
                ),
                timeout=15.0,
            )

            fact = response.text.strip()
            # Basic sanitization: strip quotes if Gemini adds them
            if (fact.startswith('"') and fact.endswith('"')) or (
                fact.startswith("'") and fact.endswith("'")
            ):
                fact = fact[1:-1]

            await interaction.followup.send(f"> {fact}")

        except TimeoutError:
            log.warning("/junkstats timed out (15s)")
            await interaction.followup.send(
                harry_error("The AI is juust a bit unresponsive. Maybe it's checking the bullpen.")
            )
        except Exception as exc:
            log.exception("/junkstats error")
            await interaction.followup.send(harry_error(safe_exc_label(exc)))


async def setup(bot: commands.Bot) -> None:
    # This is handled in commands/__init__.py for consistency with other cogs
    pass
