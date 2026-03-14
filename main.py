"""
main.py — Entry point for the Harry Discord bot.

Responsibilities:
  1. Configure logging (once, here, not at module import time)
  2. Enable pybaseball cache
  3. Instantiate HarryBot and run it

Everything else lives in bot.py, persona.py, statcast.py, and commands/.
"""

from __future__ import annotations

import logging
import os
import sys

# Set the non-interactive backend BEFORE pyplot is imported anywhere else.
# This must happen before any other project import that might pull in pyplot.
import matplotlib

matplotlib.use("Agg")

import pybaseball
import pybaseball.cache

from bot import HarryBot


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> None:
    _configure_logging()

    # Enable pybaseball's disk cache to reduce repeat network calls.
    # Called here (not at import time) so test suites can import statcast.py
    # without side-effects.
    pybaseball.cache.enable()

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        logging.critical(
            "DISCORD_TOKEN environment variable is not set. "
            "Export it before running: export DISCORD_TOKEN=your_bot_token"
        )
        sys.exit(1)

    HarryBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
