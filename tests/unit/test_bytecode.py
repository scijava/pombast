"""Tests for bytecode-floor bump classification."""

from pombast.maven._bytecode import (
    BumpClassifier,
    build_consumer_index,
    candidate_floor,
    round_up_to_lts,
)


class TestRoundUpToLts:
    def test_exact(self):
        assert round_up_to_lts(11) == 11

    def test_between(self):
        assert round_up_to_lts(16) == 17
        assert round_up_to_lts(9) == 11

    def test_above_known(self):
        assert round_up_to_lts(99) == 99


class TestConsumerIndex:
    def test_inverts_closures(self):
        closures = {
            "g:foo": ["g:guava::jar:1", "g:other::jar:1"],
            "g:bar": ["g:guava::jar:1"],
            "g:guava": [],
        }
        index = build_consumer_index(closures)
        assert index["g:guava"] == {"g:foo", "g:bar"}
        assert index["g:other"] == {"g:foo"}

    def test_ignores_malformed(self):
        index = build_consumer_index({"g:a": ["nocolons", "g:b::jar:1"]})
        assert index == {"g:b": {"g:a"}}


class TestCandidateFloor:
    def test_own_drives(self):
        # current floor was own-driven (8==own); new own is higher.
        assert candidate_floor(17, 8, 8) == 17

    def test_dependency_carries_forward(self):
        # current effective (21) was dependency-driven (> own 8); new own is 8.
        assert candidate_floor(8, 8, 21) == 21

    def test_no_dep_contribution_when_own_was_max(self):
        assert candidate_floor(11, 11, 11) == 11

    def test_all_none(self):
        assert candidate_floor(None, None, None) is None


def _classifier() -> BumpClassifier:
    floors = {"g:guava": 11, "g:foo": 17, "g:bar": 11, "g:leaf": 17}
    closures = {
        "g:foo": ["g:guava::jar:1"],
        "g:bar": ["g:guava::jar:1"],
        "g:leaf": ["g:guava::jar:1"],
        "g:guava": [],
    }
    return BumpClassifier(floors=floors, closures=closures, runtime_cap=21)


class TestClassify:
    def test_flat(self):
        result = _classifier().classify("g:foo", [("1.5", 17)])
        assert result.ladder[0].klass == "flat"
        assert result.recommended == "1.5"
        assert result.frontier_class == "flat"

    def test_local_for_leaf(self):
        # leaf at 17, bump to 21: nothing depends on it → local.
        result = _classifier().classify("g:leaf", [("2.0", 21)])
        step = result.ladder[0]
        assert step.klass == "local"
        assert step.lifted == []
        assert result.recommended is None
        assert result.frontier_class == "local"

    def test_cascading_lifts_consumer(self):
        # guava 11 → 17 lifts bar (floor 11) but not foo/leaf (already 17).
        result = _classifier().classify("g:guava", [("2.0", 17)])
        step = result.ladder[0]
        assert step.klass == "cascading"
        assert step.lifted == ["g:bar"]
        assert result.frontier_class == "cascading"

    def test_excluded_above_cap(self):
        result = _classifier().classify("g:leaf", [("9.0", 25)])
        assert result.ladder[0].klass == "excluded"
        assert result.frontier_class == "excluded"

    def test_unknown_floor(self):
        result = _classifier().classify("g:foo", [("1.5", None)])
        assert result.ladder[0].klass == "unknown"
        assert result.recommended is None
        assert result.frontier_class is None

    def test_recommends_newest_flat(self):
        # Newest-first candidates: 2.0 lifts the floor, 1.5/1.4 stay flat.
        result = _classifier().classify(
            "g:foo", [("2.0", 21), ("1.5", 17), ("1.4", 17)]
        )
        assert result.recommended == "1.5"
        # Frontier is the worst class present (2.0 raises foo's own floor).
        assert result.frontier_class in ("local", "cascading")
