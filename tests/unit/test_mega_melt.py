"""Tests for mega-melt POM generation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import pytest

from pombast.core._component import Component
from pombast.maven._mega_melt import _SYNTHETIC_VERSION, prepare_mega_melt

if TYPE_CHECKING:
    from pathlib import Path

_NS = "http://maven.apache.org/POM/4.0.0"


def _text(root: ET.Element, *path: str) -> str | None:
    """Navigate a chain of tag names and return the text of the final element."""
    elem = root
    for tag in path:
        next_elem = elem.find(f"{{{_NS}}}{tag}")
        if next_elem is None:
            return None
        elem = next_elem
    return elem.text


def _make_bom_pom(tmp_path: Path, group: str, artifact: str, version: str) -> Path:
    """Write a minimal BOM pom.xml and return its path."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    pom = tmp_path / "pom.xml"
    pom.write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>{group}</groupId>
  <artifactId>{artifact}</artifactId>
  <version>{version}</version>
  <packaging>pom</packaging>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.example</groupId>
        <artifactId>alpha</artifactId>
        <version>1.0</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>
""",
        encoding="utf-8",
    )
    return pom


def _parse_pom(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


class TestPrepareMegaMelt:
    def test_bom_copy_version_replaced(self, tmp_path):
        bom_pom = _make_bom_pom(
            tmp_path / "bom", "org.example", "my-bom", "2.0.0-SNAPSHOT"
        )
        mega_dir = tmp_path / "mega-melt"

        prepare_mega_melt(bom_pom, mega_dir, [], {})

        root = _parse_pom(mega_dir / "bom" / "pom.xml")
        assert _text(root, "version") == _SYNTHETIC_VERSION

    def test_bom_copy_preserves_group_and_artifact(self, tmp_path):
        bom_pom = _make_bom_pom(tmp_path / "bom", "org.example", "my-bom", "1.0")
        mega_dir = tmp_path / "mega-melt"

        prepare_mega_melt(bom_pom, mega_dir, [], {})

        root = _parse_pom(mega_dir / "bom" / "pom.xml")
        assert _text(root, "groupId") == "org.example"
        assert _text(root, "artifactId") == "my-bom"

    def test_mega_melt_pom_parent_points_to_copy(self, tmp_path):
        bom_pom = _make_bom_pom(tmp_path / "bom", "org.example", "my-bom", "1.0")
        mega_dir = tmp_path / "mega-melt"

        prepare_mega_melt(bom_pom, mega_dir, [], {})

        root = _parse_pom(mega_dir / "pom.xml")
        assert _text(root, "parent", "groupId") == "org.example"
        assert _text(root, "parent", "artifactId") == "my-bom"
        assert _text(root, "parent", "version") == _SYNTHETIC_VERSION
        assert _text(root, "parent", "relativePath") == "bom/pom.xml"

    def test_mega_melt_pom_packaging_is_pom(self, tmp_path):
        bom_pom = _make_bom_pom(tmp_path / "bom", "org.example", "my-bom", "1.0")
        mega_dir = tmp_path / "mega-melt"

        prepare_mega_melt(bom_pom, mega_dir, [], {})

        root = _parse_pom(mega_dir / "pom.xml")
        assert _text(root, "packaging") == "pom"

    def test_components_listed_without_version(self, tmp_path):
        bom_pom = _make_bom_pom(tmp_path / "bom", "org.example", "my-bom", "1.0")
        mega_dir = tmp_path / "mega-melt"
        components = [
            Component(group="org.foo", name="alpha", version="1.0"),
            Component(group="org.foo", name="beta", version="2.0"),
        ]

        prepare_mega_melt(bom_pom, mega_dir, components, {})

        root = _parse_pom(mega_dir / "pom.xml")
        deps = root.findall(f".//{{{_NS}}}dependencies/{{{_NS}}}dependency")
        gas = {
            (d.findtext(f"{{{_NS}}}groupId"), d.findtext(f"{{{_NS}}}artifactId"))
            for d in deps
        }
        assert ("org.foo", "alpha") in gas
        assert ("org.foo", "beta") in gas
        # No <version> in the listed dependencies.
        for dep in deps:
            assert dep.find(f"{{{_NS}}}version") is None

    def test_non_central_repos_included(self, tmp_path):
        bom_pom = _make_bom_pom(tmp_path / "bom", "org.example", "my-bom", "1.0")
        mega_dir = tmp_path / "mega-melt"
        repos = {
            "central": "https://repo1.maven.org/maven2",
            "scijava": "https://maven.scijava.org/content/groups/public",
        }

        prepare_mega_melt(bom_pom, mega_dir, [], repos)

        root = _parse_pom(mega_dir / "pom.xml")
        repo_urls = [
            r.findtext(f"{{{_NS}}}url")
            for r in root.findall(f".//{{{_NS}}}repositories/{{{_NS}}}repository")
        ]
        assert "https://maven.scijava.org/content/groups/public" in repo_urls
        assert "https://repo1.maven.org/maven2" not in repo_urls

    def test_group_inherited_from_parent(self, tmp_path):
        """groupId absent at project level but present in <parent> is resolved."""
        pom = tmp_path / "bom" / "pom.xml"
        pom.parent.mkdir(parents=True)
        pom.write_text(
            """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.example</groupId>
    <artifactId>parent-bom</artifactId>
    <version>1.0</version>
  </parent>
  <artifactId>my-bom</artifactId>
  <version>2.0-SNAPSHOT</version>
  <packaging>pom</packaging>
</project>
""",
            encoding="utf-8",
        )
        mega_dir = tmp_path / "mega-melt"

        prepare_mega_melt(pom, mega_dir, [], {})

        root = _parse_pom(mega_dir / "pom.xml")
        assert _text(root, "parent", "groupId") == "org.example"
        assert _text(root, "parent", "artifactId") == "my-bom"

    def test_missing_group_or_artifact_raises(self, tmp_path):
        pom = tmp_path / "bad.pom"
        pom.write_text(
            '<?xml version="1.0"?>'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<modelVersion>4.0.0</modelVersion>"
            "</project>",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing groupId or artifactId"):
            prepare_mega_melt(pom, tmp_path / "mega-melt", [], {})
