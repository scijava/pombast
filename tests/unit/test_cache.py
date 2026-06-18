"""Tests for caching: per-component dependency-closure success tracking."""

from dataclasses import dataclass

from pombast.cache._success import SuccessCache, closure_matches_pins
from pombast.core._component import Component


def _c(group: str, name: str, version: str) -> Component:
    return Component(group=group, name=name, version=version)


@dataclass
class _Pin:
    """Minimal stand-in for a jgo dependency in a dep_mgmt value."""

    version: str


def _pins(*entries: tuple[str, str, str, str, str]) -> dict:
    """Build a GACT-keyed dep_mgmt from (g, a, c, t, v) tuples."""
    return {(g, a, c, t): _Pin(v) for g, a, c, t, v in entries}


class TestClosureMatchesPins:
    def test_all_match(self):
        closure = ["org.scijava:a::jar:1.0", "net.imagej:b::jar:2.0"]
        pins = _pins(
            ("org.scijava", "a", "", "jar", "1.0"),
            ("net.imagej", "b", "", "jar", "2.0"),
        )
        assert closure_matches_pins(closure, pins)

    def test_version_drift(self):
        closure = ["org.scijava:a::jar:1.0"]
        pins = _pins(("org.scijava", "a", "", "jar", "2.0"))
        assert not closure_matches_pins(closure, pins)

    def test_snapshot_pin_forces_rebuild(self):
        closure = ["org.scijava:a::jar:1.0"]
        pins = _pins(("org.scijava", "a", "", "jar", "1.0-SNAPSHOT"))
        assert not closure_matches_pins(closure, pins)

    def test_unmanaged_dependency_ignored(self):
        # A dep not present in dep_mgmt cannot be validated; it must not veto.
        closure = ["org.scijava:a::jar:1.0", "com.unmanaged:x::jar:9.9"]
        pins = _pins(("org.scijava", "a", "", "jar", "1.0"))
        assert closure_matches_pins(closure, pins)

    def test_legacy_fingerprint_line_is_not_a_hit(self):
        # A line from the old SHA-256 fingerprint format (no colons) must not
        # crash and must not count as a match.
        legacy = ["a" * 64]
        assert not closure_matches_pins(legacy, _pins())

    def test_classifier_distinguishes_artifacts(self):
        # Same G:A, different classifier — GACT precision keeps them separate.
        closure = ["org.lwjgl:lwjgl:natives-linux:jar:3.3.1"]
        # Only the no-classifier variant is pinned; the natives artifact is
        # therefore unmanaged here, so it is ignored rather than mismatched.
        pins = _pins(("org.lwjgl", "lwjgl", "", "jar", "3.3.1"))
        assert closure_matches_pins(closure, pins)
        # And when the natives variant is the one that drifted, it is caught.
        pins2 = _pins(("org.lwjgl", "lwjgl", "natives-linux", "jar", "3.3.2"))
        assert not closure_matches_pins(closure, pins2)


class TestSuccessCache:
    def test_no_prior_success(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        assert not cache.has_prior_success(c, _pins())

    def test_record_and_check(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        closure = ["org.scijava:dep::jar:1.0"]
        cache.record_success(c, closure)
        pins = _pins(("org.scijava", "dep", "", "jar", "1.0"))
        assert cache.has_prior_success(c, pins)

    def test_check_fails_after_dependency_bump(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, ["org.scijava:dep::jar:1.0"])
        bumped = _pins(("org.scijava", "dep", "", "jar", "1.1"))
        assert not cache.has_prior_success(c, bumped)

    def test_hits_any_stored_closure(self, tmp_path):
        # Two different past successes; the current pins match the older one.
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, ["org.scijava:dep::jar:1.0"])
        cache.record_success(c, ["org.scijava:dep::jar:2.0"])
        assert cache.has_prior_success(
            c, _pins(("org.scijava", "dep", "", "jar", "1.0"))
        )
        assert cache.has_prior_success(
            c, _pins(("org.scijava", "dep", "", "jar", "2.0"))
        )

    def test_empty_closure_is_recorded_and_hits(self, tmp_path):
        # A component with no managed dependencies still succeeds; its (deps-only
        # empty) closure must round-trip so later runs hit the cache instead of
        # rebuilding every time. The component's own self-entry keeps the stored
        # key non-empty even here.
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, [])
        assert cache._cache_path(c).exists()
        assert cache.has_prior_success(c, _pins())
        assert cache.matching_closure(c, _pins()) == []

    def test_component_version_bump_invalidates(self, tmp_path):
        # The component's own version is part of the key: bumping it in the BOM
        # (even with no dependencies) must force a rebuild, not a stale hit.
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, [])
        # Same version still pinned in the BOM → hit.
        assert cache.has_prior_success(c, _pins(("org.scijava", "a", "", "jar", "1.0")))
        # Bumped to a never-tested version → miss.
        assert not cache.has_prior_success(
            c, _pins(("org.scijava", "a", "", "jar", "2.0"))
        )

    def test_self_entry_uses_primary_type(self, tmp_path):
        # A component whose primary artifact is pinned under a non-jar type
        # (e.g. an OSGi bundle) must match that key, not assume jar.
        cache = SuccessCache(cache_dir=tmp_path)
        c = Component(
            group="org.scijava", name="a", version="1.0", primary_type="bundle"
        )
        cache.record_success(c, [])
        # Pinned as a bundle at the same version → hit.
        assert cache.has_prior_success(
            c, _pins(("org.scijava", "a", "", "bundle", "1.0"))
        )
        # Bumped → miss (version genuinely validated, not silently ignored).
        assert not cache.has_prior_success(
            c, _pins(("org.scijava", "a", "", "bundle", "2.0"))
        )

    def test_self_entry_stripped_from_returned_closure(self, tmp_path):
        # The returned closure is the pure dependency set — the self-entry that
        # backs the version check is an implementation detail of the key.
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, ["org.scijava:dep::jar:1.0"])
        pins = _pins(
            ("org.scijava", "a", "", "jar", "1.0"),
            ("org.scijava", "dep", "", "jar", "1.0"),
        )
        assert cache.matching_closure(c, pins) == ["org.scijava:dep::jar:1.0"]

    def test_snapshot_closure_not_recorded(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, ["org.scijava:dep::jar:1.0-SNAPSHOT"])
        assert not cache._cache_path(c).exists()

    def test_duplicate_closure_not_appended(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        closure = ["org.scijava:dep::jar:1.0"]
        cache.record_success(c, closure)
        cache.record_success(c, closure)
        lines = cache._cache_path(c).read_text().splitlines()
        assert len(lines) == 1

    def test_is_snapshot(self):
        cache = SuccessCache()
        assert cache.is_snapshot(_c("org.scijava", "a", "1.0-SNAPSHOT"))
        assert not cache.is_snapshot(_c("org.scijava", "a", "1.0"))

    def test_matching_closure_returns_entries(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        closure = ["org.scijava:dep::jar:1.0", "net.imagej:b::jar:2.0"]
        cache.record_success(c, closure)
        pins = _pins(
            ("org.scijava", "dep", "", "jar", "1.0"),
            ("net.imagej", "b", "", "jar", "2.0"),
        )
        # Stored sorted; returns the matching closure entries, not a bool.
        assert cache.matching_closure(c, pins) == sorted(closure)

    def test_matching_closure_none_on_miss(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, ["org.scijava:dep::jar:1.0"])
        bumped = _pins(("org.scijava", "dep", "", "jar", "1.1"))
        assert cache.matching_closure(c, bumped) is None

    def test_legacy_depsonly_line_ignored(self, tmp_path):
        # A cache line from before self-versioning (no self-entry) must not hit,
        # forcing one rebuild so the component re-records with its own version.
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache_file = cache._cache_path(c)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("org.scijava:dep::jar:1.0\n")
        pins = _pins(("org.scijava", "dep", "", "jar", "1.0"))
        assert not cache.has_prior_success(c, pins)

    def test_different_components_isolated(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c1 = _c("org.scijava", "a", "1.0")
        c2 = _c("org.scijava", "b", "1.0")
        cache.record_success(c1, ["org.scijava:dep::jar:1.0"])
        pins = _pins(("org.scijava", "dep", "", "jar", "1.0"))
        assert cache.has_prior_success(c1, pins)
        assert not cache.has_prior_success(c2, pins)
