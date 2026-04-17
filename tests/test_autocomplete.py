"""
tests/test_autocomplete.py — Unit tests for the player-name autocomplete cache
and filter logic. All tests exercise pure functions; no Discord or network.
"""

from __future__ import annotations

import pytest

from commands.autocomplete import (
    MAX_CHOICES,
    Player,
    _build_cache,
    _player_label,
    filter_first_names,
    filter_last_names,
)

# ---------------------------------------------------------------------------
# _build_cache
# ---------------------------------------------------------------------------


class TestBuildCache:
    def test_empty_input(self) -> None:
        assert _build_cache([]) == {}

    def test_single_player(self) -> None:
        raw = [{"id": 1, "first": "Aaron", "last": "Judge", "team": "NYY", "position": "RF"}]
        cache = _build_cache(raw)
        assert len(cache) == 1
        assert cache[1] == Player(id=1, first="Aaron", last="Judge", team="NYY", position="RF")

    def test_dedup_across_seasons(self) -> None:
        """Same player in multiple seasons should collapse to one entry."""
        raw = [
            {"id": 1, "first": "Aaron", "last": "Judge", "team": "NYY", "position": "RF"},
            {"id": 1, "first": "Aaron", "last": "Judge", "team": "NYY", "position": "RF"},
            {"id": 1, "first": "Aaron", "last": "Judge", "team": "NYY", "position": "RF"},
        ]
        assert len(_build_cache(raw)) == 1

    def test_later_season_wins_team_change(self) -> None:
        """Player who switched teams mid-window should show the most-recent team."""
        raw = [
            {"id": 1, "first": "Juan", "last": "Soto", "team": "SD", "position": "RF"},
            {"id": 1, "first": "Juan", "last": "Soto", "team": "NYY", "position": "RF"},  # later
        ]
        cache = _build_cache(raw)
        assert cache[1].team == "NYY"

    def test_missing_id_skipped(self) -> None:
        raw = [{"first": "Nobody", "last": "Known", "team": "???", "position": "?"}]
        assert _build_cache(raw) == {}

    def test_missing_name_skipped(self) -> None:
        """Defensive: MLB API occasionally returns entries without a name."""
        raw = [
            {"id": 1, "first": "", "last": "Nobody", "team": "", "position": ""},
            {"id": 2, "first": "Somebody", "last": "", "team": "", "position": ""},
        ]
        assert _build_cache(raw) == {}

    def test_name_fields_are_interned(self) -> None:
        """sys.intern should collapse duplicate name strings to shared backing storage."""
        raw = [
            {"id": 1, "first": "Aaron", "last": "Judge", "team": "NYY", "position": "RF"},
            {"id": 2, "first": "Aaron", "last": "Nola", "team": "PHI", "position": "SP"},
        ]
        cache = _build_cache(raw)
        assert cache[1].first is cache[2].first  # interned same object


# ---------------------------------------------------------------------------
# _player_label
# ---------------------------------------------------------------------------


class TestPlayerLabel:
    def test_full_label(self) -> None:
        p = Player(id=1, first="Aaron", last="Judge", team="NYY", position="RF")
        assert _player_label(p) == "Aaron Judge (NYY RF)"

    def test_missing_team(self) -> None:
        p = Player(id=1, first="Aaron", last="Judge", team="", position="RF")
        assert _player_label(p) == "Aaron Judge (RF)"

    def test_missing_both(self) -> None:
        p = Player(id=1, first="Aaron", last="Judge", team="", position="")
        assert _player_label(p) == "Aaron Judge"

    def test_clipped_to_100_chars(self) -> None:
        p = Player(id=1, first="A" * 60, last="B" * 60, team="NYY", position="RF")
        assert len(_player_label(p)) == 100


# ---------------------------------------------------------------------------
# filter_first_names — exercises dedup across shared first names
# ---------------------------------------------------------------------------


def _make_cache(*specs: tuple[int, str, str, str, str]) -> dict[int, Player]:
    """Shorthand: _make_cache((1, 'Aaron', 'Judge', 'NYY', 'RF'), ...) → dict[id, Player]"""
    return {
        pid: Player(id=pid, first=first, last=last, team=team, position=pos)
        for (pid, first, last, team, pos) in specs
    }


class TestFilterFirstNames:
    def test_empty_prefix_returns_sorted_defaults(self) -> None:
        cache = _make_cache(
            (1, "Aaron", "Judge", "NYY", "RF"),
            (2, "Mike", "Trout", "LAA", "CF"),
            (3, "Bryce", "Harper", "PHI", "RF"),
        )
        results = filter_first_names(cache, "")
        assert len(results) == 3

    def test_prefix_filters_by_first_name(self) -> None:
        cache = _make_cache(
            (1, "Aaron", "Judge", "NYY", "RF"),
            (2, "Mike", "Trout", "LAA", "CF"),
            (3, "Aaron", "Nola", "PHI", "SP"),
        )
        results = filter_first_names(cache, "Aa")
        firsts = {value for _, value in results}
        assert firsts == {"Aaron"}  # Mike is excluded, 'Aaron' appears once (deduped)

    def test_distinct_first_names_not_duplicated(self) -> None:
        """Four Aarons should produce ONE 'Aaron' choice, not four."""
        cache = _make_cache(
            (1, "Aaron", "Judge", "NYY", "RF"),
            (2, "Aaron", "Nola", "PHI", "SP"),
            (3, "Aaron", "Hicks", "LAA", "OF"),
            (4, "Aaron", "Civale", "MIL", "SP"),
        )
        results = filter_first_names(cache, "Aaron")
        values = [v for _, v in results]
        assert values == ["Aaron"]  # single distinct first name

    def test_case_insensitive_prefix(self) -> None:
        cache = _make_cache((1, "Aaron", "Judge", "NYY", "RF"))
        assert filter_first_names(cache, "aAr") == [("Aaron Judge (NYY RF)", "Aaron")]

    def test_last_filter_narrows(self) -> None:
        """If user has already typed a last name, first-name choices are narrowed to matches."""
        cache = _make_cache(
            (1, "Aaron", "Judge", "NYY", "RF"),
            (2, "Aaron", "Nola", "PHI", "SP"),
            (3, "Aaron", "Hicks", "LAA", "OF"),
        )
        # Empty first prefix + last filter "nol" → only "Aaron Nola"
        results = filter_first_names(cache, "", last_filter="nol")
        assert len(results) == 1
        assert results[0][1] == "Aaron"
        assert "Nola" in results[0][0]

    def test_limit_caps_at_max_choices(self) -> None:
        cache = {
            i: Player(id=i, first=f"Chris{i:03d}", last="Smith", team="NYY", position="OF")
            for i in range(50)
        }
        assert len(filter_first_names(cache, "Chris", limit=MAX_CHOICES)) == MAX_CHOICES

    def test_label_includes_team_and_position(self) -> None:
        cache = _make_cache((1, "Aaron", "Judge", "NYY", "RF"))
        label, _ = filter_first_names(cache, "A")[0]
        assert "NYY" in label
        assert "RF" in label


# ---------------------------------------------------------------------------
# filter_last_names — mirror symmetry with cross-field narrowing
# ---------------------------------------------------------------------------


class TestFilterLastNames:
    def test_prefix_filters_by_last_name(self) -> None:
        cache = _make_cache(
            (1, "Aaron", "Judge", "NYY", "RF"),
            (2, "Mike", "Trout", "LAA", "CF"),
        )
        results = filter_last_names(cache, "Ju")
        assert [v for _, v in results] == ["Judge"]

    def test_first_filter_narrows(self) -> None:
        """After picking first_name=Aaron, last-name choices should be Aarons only."""
        cache = _make_cache(
            (1, "Aaron", "Judge", "NYY", "RF"),
            (2, "Aaron", "Nola", "PHI", "SP"),
            (3, "Mookie", "Betts", "LAD", "OF"),
        )
        results = filter_last_names(cache, "", first_filter="Aaron")
        values = {v for _, v in results}
        assert values == {"Judge", "Nola"}
        assert "Betts" not in values

    def test_distinct_last_names_not_duplicated(self) -> None:
        cache = _make_cache(
            (1, "Adolis", "Garcia", "TEX", "RF"),
            (2, "Aramis", "Garcia", "OAK", "C"),
            (3, "Avisail", "Garcia", "MIA", "OF"),
        )
        results = filter_last_names(cache, "Gar")
        assert [v for _, v in results] == ["Garcia"]

    def test_empty_result_on_no_match(self) -> None:
        cache = _make_cache((1, "Aaron", "Judge", "NYY", "RF"))
        assert filter_last_names(cache, "Zzz") == []


# ---------------------------------------------------------------------------
# Memory-footprint smoke check — frozen+slots Player
# ---------------------------------------------------------------------------


class TestPlayerDataclass:
    def test_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        p = Player(id=1, first="A", last="B", team="C", position="D")
        with pytest.raises(FrozenInstanceError):
            p.first = "X"  # ty: ignore[invalid-assignment]

    def test_slots_no_dict(self) -> None:
        """slots=True means no __dict__, saves ~60 bytes per instance."""
        p = Player(id=1, first="A", last="B", team="C", position="D")
        assert not hasattr(p, "__dict__")
