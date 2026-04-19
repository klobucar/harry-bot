"""
persona.py — Harry Doyle's voice.

Pure Python: no Discord, no pybaseball. Safe to import anywhere, including tests.
"""

from __future__ import annotations

import random

HARRY_ERRORS: list[str] = [
    "Juuust a bit outside. Try again, pal.",
    "In case you haven't noticed, and judging by your input you haven't, that player doesn't exist.",
    "That's all we got? One goddamn hit? No data available.",
    "You may run like Mays, but you type like crap. Player not found.",
    "The post-game show is brought to you by... Christ, I can't find it. No results.",
    "They're paying me in peanuts and you can't even give me a real name to look up.",
    "Wild thing, I think I love you — but I want to know for sure. And right now I've got nothing.",
    "How can these guys not get excited about baseball? The API sure isn't.",
    "Strike two! ...that was actually ball four, but there's no data either way.",
    "The Indians have managed to lose this one before it even started. Empty dataset.",
    "He is GONE! ...just like the data you were looking for. Completely gone.",
    "I don't know if that's a good pitch or a bad pitch, because I can't find any pitches at all.",
    "Monty, tell 'em what we've got. Monty: nothing. Right.",
    "Straight from the gut — or whatever it is I've been drinking — that search came up empty.",
    "We're heading into extra innings on this error. My glove's got a better search record than you.",
    "The signal's fading out here... or maybe the AI just went to the bar. Not responding, pal.",
]


def harry_error(extra: str = "") -> str:
    """Return a random in-character Harry Doyle error message."""
    base = random.choice(HARRY_ERRORS)  # noqa: S311
    if extra:
        return f"{base}\n-# *(Technical detail: {extra})*"
    return base


def safe_exc_label(exc: BaseException) -> str:
    """Short, leak-free label for an unexpected exception.

    Returns the class name plus an HTTP status code when the exception is
    a requests.HTTPError. Avoids surfacing message bodies, file paths,
    or stack frames — those go to the log via log.exception().
    """
    name = type(exc).__name__
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        return f"{name} {status}"
    return name
