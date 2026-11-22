"""
logging_config.py — structlog-over-stdlib logging setup.

structlog sits on top of the stdlib `logging` module so that logs from
libraries that use stdlib logging (discord.py, httpx, bigleague) flow through
the same processor pipeline and come out in the same shape as our own
structured events.

Renderer is env-switched:
  * JSON to stdout in production (Fly captures stdout — greppable/queryable).
    Enabled when HARRY_JSON_LOGS is set, or automatically when FLY_APP_NAME
    is present (i.e. running on Fly).
  * Pretty colorized console locally otherwise.

Log level comes from LOG_LEVEL (default INFO).

Usage:
    from logging_config import configure_logging, get_logger
    configure_logging()           # once, at startup
    log = get_logger("harry")
    log.info("command.done", command="spraychart", wall_ms=412, rss_mb=164)
"""

from __future__ import annotations

import logging
import os
import sys

import structlog

__all__ = ["configure_logging", "current_rss_mb", "get_logger"]


def _want_json() -> bool:
    if os.environ.get("HARRY_JSON_LOGS"):
        return True
    # Fly sets FLY_APP_NAME in the runtime environment.
    return bool(os.environ.get("FLY_APP_NAME"))


def configure_logging() -> None:
    """Configure structlog + stdlib logging. Idempotent; call once at startup."""
    level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)

    # Processors shared by structlog-native and stdlib ("foreign") log records.
    shared: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared,
            # Hand the event dict off to the stdlib ProcessorFormatter.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if _want_json()
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        # `foreign_pre_chain` runs on records from stdlib loggers (discord, httpx,
        # bigleague) so they get the same level/timestamp/logger-name fields.
        foreign_pre_chain=[*shared, structlog.processors.format_exc_info],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy third-party loggers (these emit per-request at INFO/DEBUG).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger (optionally named)."""
    return structlog.get_logger(name)


def current_rss_mb() -> float | None:
    """Best-effort current resident-set size in MiB.

    Reads /proc/self/statm on Linux (the Fly runtime); returns None where it
    isn't available (e.g. macOS dev box) so callers can simply omit the field.
    """
    try:
        with open("/proc/self/statm", encoding="ascii") as fh:  # noqa: PTH123
            pages = int(fh.read().split()[1])  # resident pages
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round(pages * page_size / (1024 * 1024), 1)
    except OSError, ValueError, IndexError:
        return None
