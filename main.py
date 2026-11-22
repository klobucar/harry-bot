"""
main.py — Entry point for the Harry Discord bot.

Responsibilities:
  1. Configure logging (once, here, not at module import time)
  2. Quiet noisy third-party loggers
  3. Instantiate HarryBot and run it

The baseball data/plot layer (bigleague) manages its own on-disk parquet +
Bloom-filter cache automatically; no cache setup is needed here.

Everything else lives in bot.py, persona.py, statcast.py, and commands/.
"""

from __future__ import annotations

import os
import sys

from bot import HarryBot
from logging_config import configure_logging, get_logger


def main() -> None:
    configure_logging()

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        log = get_logger("harry")
        log.critical(
            "DISCORD_TOKEN environment variable is not set. "
            "Export it before running: export DISCORD_TOKEN=your_bot_token"
        )
        sys.exit(1)

    # log_handler=None: we own the root logging handler (configure_logging),
    # so discord.py must not install its own.
    HarryBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
