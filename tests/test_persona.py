"""
tests/test_persona.py — Unit tests for Harry Doyle's persona logic.
"""

from __future__ import annotations

from persona import HARRY_ERRORS, harry_error


class TestHarryPersona:
    def test_harry_error_returns_string(self) -> None:
        """Verify that harry_error returns a non-empty string."""
        msg = harry_error()
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_harry_error_picks_from_list(self) -> None:
        """Verify that the base message is one of the predefined HARRY_ERRORS."""
        msg = harry_error()
        # Strip the technical detail if present to match the base list
        base_msg = msg.split("\n-#")[0]
        assert base_msg in HARRY_ERRORS

    def test_harry_error_includes_technical_detail(self) -> None:
        """Verify that technical details are correctly appended with Discord markdown."""
        detail = "403 Forbidden"
        msg = harry_error(detail)
        assert detail in msg
        # Check for the specific small-text markdown used in persona.py
        assert "-# *(Technical detail: 403 Forbidden)*" in msg

    def test_randomness(self) -> None:
        """Smoke test for randomness: multiple calls should eventually yield different messages."""
        messages = {harry_error() for _ in range(50)}
        # Statistically, with 15+ messages, we should see more than one unique message in 50 tries.
        assert len(messages) > 1

    def test_all_base_messages_are_valid(self) -> None:
        """Verify all messages in HARRY_ERRORS are non-empty strings."""
        for error in HARRY_ERRORS:
            assert isinstance(error, str)
            assert len(error.strip()) > 0
