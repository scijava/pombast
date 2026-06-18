"""Tests for remove-tests test-class deletion."""

import logging
from pathlib import Path

from pombast.core._pipeline import remove_test_classes


def _write_class(test_root: Path, fqn: str) -> Path:
    """Create an empty .java file for a fully-qualified class name."""
    path = test_root.joinpath(*fqn.split(".")).with_suffix(".java")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// stub\n")
    return path


def test_removes_named_class(tmp_path: Path) -> None:
    test_root = tmp_path / "src" / "test" / "java"
    target = _write_class(test_root, "com.example.foo.FooTest")
    keep = _write_class(test_root, "com.example.foo.BarTest")

    remove_test_classes(test_root, ["com.example.foo.FooTest"])

    assert not target.exists()
    assert keep.exists()


def test_fqn_disambiguates_same_simple_name(tmp_path: Path) -> None:
    test_root = tmp_path / "src" / "test" / "java"
    target = _write_class(test_root, "com.example.a.FooTest")
    other = _write_class(test_root, "com.example.b.FooTest")

    remove_test_classes(test_root, ["com.example.a.FooTest"])

    assert not target.exists()
    assert other.exists()


def test_missing_class_warns_by_default(tmp_path: Path, caplog) -> None:
    test_root = tmp_path / "src" / "test" / "java"
    test_root.mkdir(parents=True)

    with caplog.at_level(logging.WARNING):
        remove_test_classes(test_root, ["com.example.MissingTest"])

    assert any("MissingTest" in r.message for r in caplog.records)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_missing_class_silent_when_warn_missing_false(tmp_path: Path, caplog) -> None:
    test_root = tmp_path / "src" / "test" / "java"
    test_root.mkdir(parents=True)

    with caplog.at_level(logging.WARNING):
        remove_test_classes(test_root, ["com.example.MissingTest"], warn_missing=False)

    assert not any(r.levelno == logging.WARNING for r in caplog.records)
