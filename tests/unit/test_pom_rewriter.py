"""Tests for POM dependency version rewriting."""

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock

from bombast.maven._pom_rewriter import patch_pom_urls, rewrite_pom_versions

NS = "http://maven.apache.org/POM/4.0.0"


def _make_dep(version: str, scope: str = "compile") -> MagicMock:
    """Create a mock Dependency with version and scope attributes."""
    dep = MagicMock()
    dep.version = version
    dep.scope = scope
    return dep


def _write_pom(tmp_path: Path, xml_content: str) -> Path:
    pom = tmp_path / "pom.xml"
    pom.write_text(xml_content)
    return pom


def _parse(pom: Path) -> ET.Element:
    return ET.parse(pom).getroot()


SIMPLE_POM = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="{NS}">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0.0</version>

  <dependencies>
    <dependency>
      <groupId>org.foo</groupId>
      <artifactId>bar</artifactId>
      <version>1.0.0</version>
    </dependency>
    <dependency>
      <groupId>org.foo</groupId>
      <artifactId>baz</artifactId>
    </dependency>
    <dependency>
      <groupId>org.unknown</groupId>
      <artifactId>not-in-bom</artifactId>
      <version>9.9.9</version>
    </dependency>
  </dependencies>
</project>
"""


class TestRewriteDependencyVersions:
    def test_rewrites_existing_version(self, tmp_path):
        pom = _write_pom(tmp_path, SIMPLE_POM)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
            ("org.foo", "baz", "", "jar"): _make_dep("3.0.0"),
        }

        count = rewrite_pom_versions(pom, dep_mgmt)

        assert count == 2
        root = _parse(pom)
        # Find deps outside dependencyManagement.
        all_deps = list(root.iter(f"{{{NS}}}dependency"))
        bar = [d for d in all_deps if d.find(f"{{{NS}}}artifactId").text == "bar"]
        assert len(bar) == 2
        # The one in <dependencies> (not in <dependencyManagement>) should be rewritten.
        deps_section = root.find(f"{{{NS}}}dependencies")
        bar_in_deps = [
            d
            for d in deps_section.findall(f"{{{NS}}}dependency")
            if d.find(f"{{{NS}}}artifactId").text == "bar"
        ][0]
        assert bar_in_deps.find(f"{{{NS}}}version").text == "2.0.0"

    def test_adds_missing_version(self, tmp_path):
        pom = _write_pom(tmp_path, SIMPLE_POM)
        dep_mgmt = {
            ("org.foo", "baz", "", "jar"): _make_dep("3.0.0"),
        }

        count = rewrite_pom_versions(pom, dep_mgmt)

        assert count == 1
        root = _parse(pom)
        deps_section = root.find(f"{{{NS}}}dependencies")
        baz = [
            d
            for d in deps_section.findall(f"{{{NS}}}dependency")
            if d.find(f"{{{NS}}}artifactId").text == "baz"
        ][0]
        assert baz.find(f"{{{NS}}}version").text == "3.0.0"

    def test_skips_deps_not_in_bom(self, tmp_path):
        pom = _write_pom(tmp_path, SIMPLE_POM)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
        }

        rewrite_pom_versions(pom, dep_mgmt)

        root = _parse(pom)
        deps_section = root.find(f"{{{NS}}}dependencies")
        unknown = [
            d
            for d in deps_section.findall(f"{{{NS}}}dependency")
            if d.find(f"{{{NS}}}artifactId").text == "not-in-bom"
        ][0]
        assert unknown.find(f"{{{NS}}}version").text == "9.9.9"

    def test_skips_already_correct_version(self, tmp_path):
        pom = _write_pom(tmp_path, SIMPLE_POM)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("1.0.0"),
        }

        count = rewrite_pom_versions(pom, dep_mgmt)
        assert count == 0

    def test_rewrites_deps_in_profiles(self, tmp_path):
        pom_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="{NS}">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.example</groupId>
  <artifactId>profiled</artifactId>
  <version>1.0.0</version>

  <profiles>
    <profile>
      <id>special</id>
      <dependencies>
        <dependency>
          <groupId>org.foo</groupId>
          <artifactId>bar</artifactId>
          <version>1.0.0</version>
        </dependency>
      </dependencies>
    </profile>
  </profiles>
</project>
"""
        pom = _write_pom(tmp_path, pom_xml)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
        }

        count = rewrite_pom_versions(pom, dep_mgmt)

        assert count == 1

    def test_handles_property_reference_version(self, tmp_path):
        pom_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="{NS}">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.example</groupId>
  <artifactId>propref</artifactId>
  <version>1.0.0</version>

  <dependencies>
    <dependency>
      <groupId>org.foo</groupId>
      <artifactId>bar</artifactId>
      <version>${{bar.version}}</version>
    </dependency>
  </dependencies>
</project>
"""
        pom = _write_pom(tmp_path, pom_xml)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("5.0.0"),
        }

        count = rewrite_pom_versions(pom, dep_mgmt)

        assert count == 1

    def test_returns_zero_for_empty_dep_mgmt(self, tmp_path):
        pom = _write_pom(tmp_path, SIMPLE_POM)
        count = rewrite_pom_versions(pom, {})
        assert count == 0

    def test_preserves_other_elements(self, tmp_path):
        pom_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="{NS}">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.example</groupId>
  <artifactId>with-extras</artifactId>
  <version>1.0.0</version>

  <dependencies>
    <dependency>
      <groupId>org.foo</groupId>
      <artifactId>bar</artifactId>
      <version>1.0.0</version>
      <scope>test</scope>
      <exclusions>
        <exclusion>
          <groupId>org.unwanted</groupId>
          <artifactId>thing</artifactId>
        </exclusion>
      </exclusions>
    </dependency>
  </dependencies>
</project>
"""
        pom = _write_pom(tmp_path, pom_xml)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
        }

        rewrite_pom_versions(pom, dep_mgmt)

        root = _parse(pom)
        deps_section = root.find(f"{{{NS}}}dependencies")
        dep = deps_section.find(f"{{{NS}}}dependency")
        assert dep.find(f"{{{NS}}}scope").text == "test"
        excl = dep.find(f".//{{{NS}}}exclusion/{{{NS}}}groupId")
        assert excl.text == "org.unwanted"


class TestInjectDependencyManagement:
    def test_creates_dep_mgmt_section(self, tmp_path):
        pom = _write_pom(tmp_path, SIMPLE_POM)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
            ("org.foo", "baz", "", "jar"): _make_dep("3.0.0"),
        }

        rewrite_pom_versions(pom, dep_mgmt)

        root = _parse(pom)
        dm = root.find(f"{{{NS}}}dependencyManagement")
        assert dm is not None
        dm_deps = dm.findall(f"{{{NS}}}dependencies/{{{NS}}}dependency")
        assert len(dm_deps) == 2

        by_artifact = {d.find(f"{{{NS}}}artifactId").text: d for d in dm_deps}
        assert by_artifact["bar"].find(f"{{{NS}}}version").text == "2.0.0"
        assert by_artifact["baz"].find(f"{{{NS}}}version").text == "3.0.0"

    def test_preserves_existing_dep_mgmt(self, tmp_path):
        pom_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="{NS}">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.example</groupId>
  <artifactId>has-dm</artifactId>
  <version>1.0.0</version>

  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.existing</groupId>
        <artifactId>lib</artifactId>
        <version>1.0.0</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>
"""
        pom = _write_pom(tmp_path, pom_xml)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
        }

        rewrite_pom_versions(pom, dep_mgmt)

        root = _parse(pom)
        dm_deps = root.findall(
            f"{{{NS}}}dependencyManagement/{{{NS}}}dependencies/{{{NS}}}dependency"
        )
        artifacts = [d.find(f"{{{NS}}}artifactId").text for d in dm_deps]
        assert "lib" in artifacts
        assert "bar" in artifacts

    def test_updates_existing_dep_mgmt_entry(self, tmp_path):
        pom_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="{NS}">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.example</groupId>
  <artifactId>has-dm</artifactId>
  <version>1.0.0</version>

  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.foo</groupId>
        <artifactId>bar</artifactId>
        <version>1.0.0</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>
"""
        pom = _write_pom(tmp_path, pom_xml)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
        }

        rewrite_pom_versions(pom, dep_mgmt)

        root = _parse(pom)
        dm_deps = root.findall(
            f"{{{NS}}}dependencyManagement/{{{NS}}}dependencies/{{{NS}}}dependency"
        )
        # Should update, not duplicate.
        assert len(dm_deps) == 1
        assert dm_deps[0].find(f"{{{NS}}}version").text == "2.0.0"

    def test_includes_non_jar_type(self, tmp_path):
        pom = _write_pom(tmp_path, SIMPLE_POM)
        dep_mgmt = {
            ("org.foo", "plugin", "", "maven-plugin"): _make_dep("1.0.0"),
        }

        rewrite_pom_versions(pom, dep_mgmt)

        root = _parse(pom)
        dm_deps = root.findall(
            f"{{{NS}}}dependencyManagement/{{{NS}}}dependencies/{{{NS}}}dependency"
        )
        plugin = [d for d in dm_deps if d.find(f"{{{NS}}}artifactId").text == "plugin"][
            0
        ]
        assert plugin.find(f"{{{NS}}}type").text == "maven-plugin"

    def test_does_not_rewrite_dep_mgmt_deps_as_direct(self, tmp_path):
        """Prong 2 should not touch deps inside <dependencyManagement>."""
        pom_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="{NS}">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.example</groupId>
  <artifactId>test</artifactId>
  <version>1.0.0</version>

  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.foo</groupId>
        <artifactId>bar</artifactId>
        <version>1.0.0</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>
"""
        pom = _write_pom(tmp_path, pom_xml)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
        }

        # Prong 1 updates the dep_mgmt entry; prong 2 should not count it.
        count = rewrite_pom_versions(pom, dep_mgmt)
        assert count == 0

    def test_both_prongs_together(self, tmp_path):
        pom = _write_pom(tmp_path, SIMPLE_POM)
        dep_mgmt = {
            ("org.foo", "bar", "", "jar"): _make_dep("2.0.0"),
            ("org.foo", "baz", "", "jar"): _make_dep("3.0.0"),
        }

        count = rewrite_pom_versions(pom, dep_mgmt)

        # Prong 2 rewrites direct deps.
        assert count == 2
        root = _parse(pom)
        # Prong 1 injected dep_mgmt.
        dm = root.find(f"{{{NS}}}dependencyManagement")
        assert dm is not None
        dm_deps = dm.findall(f"{{{NS}}}dependencies/{{{NS}}}dependency")
        assert len(dm_deps) == 2
        # Direct deps also rewritten.
        deps_section = root.find(f"{{{NS}}}dependencies")
        bar = [
            d
            for d in deps_section.findall(f"{{{NS}}}dependency")
            if d.find(f"{{{NS}}}artifactId").text == "bar"
        ][0]
        assert bar.find(f"{{{NS}}}version").text == "2.0.0"


class TestPatchPomUrls:
    def test_patches_http_to_https(self, tmp_path):
        pom = _write_pom(
            tmp_path,
            """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <repositories>
    <repository>
      <id>imagej.public</id>
      <url>http://maven.imagej.net/content/groups/public</url>
    </repository>
  </repositories>
</project>
""",
        )
        assert patch_pom_urls(pom) is True
        text = pom.read_text()
        assert "https://maven.imagej.net/content/groups/public" in text
        assert "http://maven.imagej.net" not in text

    def test_patches_xsd_url(self, tmp_path):
        pom = _write_pom(
            tmp_path,
            """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
  xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
    http://maven.apache.org/xsd/maven-4.0.0.xsd">
</project>
""",
        )
        assert patch_pom_urls(pom) is True
        text = pom.read_text()
        assert "https://maven.apache.org/xsd/maven-4.0.0.xsd" in text
        # The namespace URL should NOT be changed.
        assert "http://maven.apache.org/POM/4.0.0" in text

    def test_preserves_pom_namespace(self, tmp_path):
        pom = _write_pom(
            tmp_path,
            """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
</project>
""",
        )
        assert patch_pom_urls(pom) is False

    def test_no_change_when_already_https(self, tmp_path):
        pom = _write_pom(
            tmp_path,
            """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
  <repositories>
    <repository>
      <url>https://repo.maven.apache.org/maven2</url>
    </repository>
  </repositories>
</project>
""",
        )
        assert patch_pom_urls(pom) is False

    def test_patches_multiple_urls(self, tmp_path):
        pom = _write_pom(
            tmp_path,
            """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <repositories>
    <repository>
      <url>http://maven.imagej.net/content/groups/public</url>
    </repository>
    <repository>
      <url>http://maven.scijava.org/content/groups/public</url>
    </repository>
  </repositories>
</project>
""",
        )
        assert patch_pom_urls(pom) is True
        text = pom.read_text()
        assert "https://maven.imagej.net" in text
        assert "https://maven.scijava.org" in text
        assert "http://maven.apache.org/POM/4.0.0" in text
        assert text.count("http://") == 1  # only the namespace
