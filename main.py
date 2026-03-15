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

# --- Matplotlib Memory Optimization ---
# Force matplotlib to use the headless 'Agg' backend.
# This must happen before any other module imports matplotlib.pyplot.
import matplotlib
matplotlib.use("Agg")
# --------------------------------------

from bot import HarryBot


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    
    # Disable overly verbose pybaseball caching logs
    logging.getLogger("pybaseball").setLevel(logging.WARNING)


def main() -> None:
    _configure_logging()

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
