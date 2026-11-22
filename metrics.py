"""
metrics.py — Prometheus metrics, collected by Fly into its managed Grafana.

With a ``[metrics]`` section in fly.toml, Fly collects ``/metrics`` every 15
seconds and keeps about 15 days of data, queryable at fly-metrics.net. The
endpoint starts only when ``HARRY_METRICS_PORT`` is set (fly.toml sets it), so
local runs and tests don't open a port.

prometheus_client also exports process metrics on Linux, such as
``process_resident_memory_bytes``, so memory is covered without a custom gauge.

Fly adds ``app``, ``region``, ``host`` and ``instance`` labels to every series
and overwrites any custom label with the same name, so don't use those names
here.
"""

from __future__ import annotations

import logging
import os

from prometheus_client import Counter, Histogram, disable_created_metrics, start_http_server

log = logging.getLogger("harry")

# Skip the *_created timestamp series. Grafana doesn't use them, and they
# double the series count.
disable_created_metrics()

COMMAND_DURATION = Histogram(
    "harry_command_duration_seconds",
    "Slash command wall time, from the interaction check until it finishes or fails.",
    ["command", "outcome"],
    # Plots and FanGraphs pulls take seconds; /junkstats can take up to 30 s.
    buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0),
)

JUNKSTATS_ATTEMPTS = Counter(
    "harry_junkstats_attempts",
    "/junkstats Gemini calls by model and result (ok, timeout, or the HTTP status).",
    ["model", "result"],
)


def start_metrics_server() -> int | None:
    """Serve /metrics on HARRY_METRICS_PORT. Returns the port, or None if off.

    Never raises: losing metrics must not stop Harry from starting.
    """
    raw = os.environ.get("HARRY_METRICS_PORT", "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        log.warning("Ignoring invalid HARRY_METRICS_PORT: %r", raw)
        return None
    port = int(raw)
    try:
        # Fly collects from 0.0.0.0. With no [[services]] entry for this port,
        # it isn't exposed publicly.
        start_http_server(port, addr="0.0.0.0")  # noqa: S104
    except OSError:
        log.exception("Could not start the metrics server on port %d", port)
        return None
    log.info("Serving Prometheus metrics on port %d at /metrics", port)
    return port
