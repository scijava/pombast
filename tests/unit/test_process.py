"""Tests for Maven subprocess helpers."""

from unittest import mock

import pombast.util._process as proc


def _reset_mvn_cache():
    proc._mvn_cmd = None


def test_resolve_mvn_delegates_to_jgo():
    _reset_mvn_cache()
    fake = mock.Mock(return_value="/opt/maven/bin/mvn")
    with mock.patch("jgo.util.mvn.ensure_maven_available", fake):
        assert proc._resolve_mvn() == "/opt/maven/bin/mvn"
    fake.assert_called_once()


def test_resolve_mvn_is_memoized():
    _reset_mvn_cache()
    fake = mock.Mock(return_value="/opt/maven/bin/mvn")
    with mock.patch("jgo.util.mvn.ensure_maven_available", fake):
        proc._resolve_mvn()
        proc._resolve_mvn()
        proc._resolve_mvn()
    # Resolved only once despite repeated calls (and would not call again now).
    fake.assert_called_once()


def test_resolve_mvn_returns_str():
    _reset_mvn_cache()
    from pathlib import Path

    with mock.patch(
        "jgo.util.mvn.ensure_maven_available",
        return_value=Path("/usr/bin/mvn"),
    ):
        result = proc._resolve_mvn()
    assert result == "/usr/bin/mvn"
    assert isinstance(result, str)
