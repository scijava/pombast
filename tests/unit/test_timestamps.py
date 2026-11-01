"""Tests for UTC normalization of release timestamps."""

from datetime import UTC, datetime, timedelta, timezone

from pombast.cache._pom_timestamp import PomTimestampCache
from pombast.status._drift import drift_text
from pombast.status._query import _parse_ts
from pombast.util._time import as_utc


def test_parse_ts_is_utc_aware():
    assert _parse_ts("20261021072800") == datetime(2026, 10, 21, 7, 28, tzinfo=UTC)


def test_as_utc_naive_assumed_utc():
    naive = datetime(2026, 10, 21, 7, 28)
    assert as_utc(naive) == datetime(2026, 10, 21, 7, 28, tzinfo=UTC)


def test_as_utc_converts_offset():
    cdt = datetime(2026, 10, 21, 2, 28, tzinfo=timezone(timedelta(hours=-5)))
    result = as_utc(cdt)
    assert result.tzinfo == UTC
    assert result == datetime(2026, 10, 21, 7, 28, tzinfo=UTC)


def test_pom_timestamp_cache_upgrades_naive_entries(tmp_path):
    """Entries written by older pombast versions are naive; read them as UTC."""
    cache = PomTimestampCache(tmp_path)
    cache.put("org.example", "foo", "1.0", datetime(2026, 10, 21, 7, 28))
    assert cache.get("org.example", "foo", "1.0") == datetime(
        2026, 10, 21, 7, 28, tzinfo=UTC
    )


class _Entry:
    def __init__(self, last_vetted, last_updated):
        self.last_vetted = last_vetted
        self.last_updated = last_updated


def test_drift_with_vetting_override_and_jgo_timestamps():
    """
    Regression test: a vetting override (parsed by pombast) and lastUpdated
    (from jgo, UTC-aware since jgo 3.2.0) must be comparable.
    """
    vetted = _parse_ts("20261020000000")
    updated = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)
    assert drift_text(_Entry(vetted, updated)) == "24h"
