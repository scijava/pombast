"""Tests for locating the module subdirectory that builds a component."""

from pathlib import Path

from pombast.core._component import Component
from pombast.maven._reactor import locate_module_dir

NS = "http://maven.apache.org/POM/4.0.0"


def _pom(group: str | None, artifact: str, parent_group: str | None = None) -> str:
    group_elem = f"  <groupId>{group}</groupId>\n" if group else ""
    parent = (
        f"  <parent>\n    <groupId>{parent_group}</groupId>\n"
        f"    <artifactId>some-parent</artifactId>\n"
        f"    <version>1.0.0</version>\n  </parent>\n"
        if parent_group
        else ""
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<project xmlns="{NS}">\n'
        f"  <modelVersion>4.0.0</modelVersion>\n"
        f"{parent}{group_elem}"
        f"  <artifactId>{artifact}</artifactId>\n"
        f"  <version>1.0.0</version>\n"
        f"</project>\n"
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_single_module_returns_root(tmp_path: Path) -> None:
    _write(tmp_path / "pom.xml", _pom("org.example", "my-app"))
    component = Component(group="org.example", name="my-app", version="1.0.0")
    assert locate_module_dir(tmp_path, component) == tmp_path


def test_nested_module_matched(tmp_path: Path) -> None:
    # Aggregator root with a different artifactId than any managed component.
    _write(tmp_path / "pom.xml", _pom("org.bonej", "pom-bonej"))
    _write(tmp_path / "Modern" / "ops" / "pom.xml", _pom("org.bonej", "bonej-ops"))
    _write(
        tmp_path / "Modern" / "wrapperPlugins" / "pom.xml",
        _pom("org.bonej", "bonej-plugins"),
    )
    component = Component(group="org.bonej", name="bonej-plugins", version="7.2.0")
    assert (
        locate_module_dir(tmp_path, component)
        == tmp_path / "Modern" / "wrapperPlugins"
    )


def test_group_inherited_from_parent(tmp_path: Path) -> None:
    # scijava/scijava topology: module omits groupId; parent is pom-scijava.
    _write(tmp_path / "pom.xml", _pom("org.scijava", "scijava-aggregator"))
    _write(
        tmp_path / "scijava-common3" / "pom.xml",
        _pom(None, "scijava-common3", parent_group="org.scijava"),
    )
    component = Component(group="org.scijava", name="scijava-common3", version="1.0.0")
    assert locate_module_dir(tmp_path, component) == tmp_path / "scijava-common3"


def test_no_match_returns_none(tmp_path: Path) -> None:
    _write(tmp_path / "pom.xml", _pom("org.example", "my-app"))
    component = Component(group="org.example", name="absent", version="1.0.0")
    assert locate_module_dir(tmp_path, component) is None


def test_target_dirs_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "pom.xml", _pom("org.example", "aggregator"))
    _write(tmp_path / "mod" / "pom.xml", _pom("org.example", "real"))
    # A stray POM under target/ must never win.
    _write(
        tmp_path / "mod" / "target" / "pom.xml", _pom("org.example", "real")
    )
    component = Component(group="org.example", name="real", version="1.0.0")
    assert locate_module_dir(tmp_path, component) == tmp_path / "mod"
