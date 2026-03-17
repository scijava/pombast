"""Tests for caching: fingerprinting and success tracking."""

from bombast.cache._fingerprint import fingerprint
from bombast.cache._success import SuccessCache
from bombast.core._component import Component


def _c(group: str, name: str, version: str) -> Component:
    return Component(group=group, name=name, version=version)


class TestFingerprint:
    def test_deterministic(self):
        components = [_c("org.scijava", "a", "1.0"), _c("net.imagej", "b", "2.0")]
        fp1 = fingerprint(components)
        fp2 = fingerprint(components)
        assert fp1 == fp2

    def test_order_independent(self):
        c1 = [_c("org.scijava", "a", "1.0"), _c("net.imagej", "b", "2.0")]
        c2 = [_c("net.imagej", "b", "2.0"), _c("org.scijava", "a", "1.0")]
        assert fingerprint(c1) == fingerprint(c2)

    def test_version_change(self):
        c1 = [_c("org.scijava", "a", "1.0")]
        c2 = [_c("org.scijava", "a", "2.0")]
        assert fingerprint(c1) != fingerprint(c2)

    def test_empty(self):
        fp = fingerprint([])
        assert len(fp) == 64  # SHA-256 hex digest length


class TestSuccessCache:
    def test_no_prior_success(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        assert not cache.has_prior_success(c, "abc123")

    def test_record_and_check(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, "abc123")
        assert cache.has_prior_success(c, "abc123")

    def test_different_fingerprint(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, "abc123")
        assert not cache.has_prior_success(c, "def456")

    def test_multiple_fingerprints(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c = _c("org.scijava", "a", "1.0")
        cache.record_success(c, "first")
        cache.record_success(c, "second")
        assert cache.has_prior_success(c, "first")
        assert cache.has_prior_success(c, "second")

    def test_is_snapshot(self):
        cache = SuccessCache()
        assert cache.is_snapshot(_c("org.scijava", "a", "1.0-SNAPSHOT"))
        assert not cache.is_snapshot(_c("org.scijava", "a", "1.0"))

    def test_different_components_isolated(self, tmp_path):
        cache = SuccessCache(cache_dir=tmp_path)
        c1 = _c("org.scijava", "a", "1.0")
        c2 = _c("org.scijava", "b", "1.0")
        cache.record_success(c1, "abc123")
        assert cache.has_prior_success(c1, "abc123")
        assert not cache.has_prior_success(c2, "abc123")
