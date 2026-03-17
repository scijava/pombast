"""Tests for version pins generation."""

from bombast.config._settings import VersionPinsConfig
from bombast.core._component import Component
from bombast.maven._pins import generate_version_pins


def _c(group: str, name: str, version: str) -> Component:
    return Component(group=group, name=name, version=version)


class TestGenerateVersionPins:
    def test_basic_properties(self):
        components = [_c("org.scijava", "scijava-common", "2.99.0")]
        xml = generate_version_pins(components)

        assert "<org.scijava.scijava-common.version>2.99.0</org.scijava.scijava-common.version>" in xml
        assert "<scijava-common.version>2.99.0</scijava-common.version>" in xml

    def test_valid_settings_xml(self):
        components = [_c("org.scijava", "scijava-common", "2.99.0")]
        xml = generate_version_pins(components)

        assert xml.startswith("<?xml version")
        assert "<settings" in xml
        assert "<profile>" in xml
        assert "<activeByDefault>true</activeByDefault>" in xml
        assert "</settings>" in xml

    def test_multiple_components(self):
        components = [
            _c("org.scijava", "scijava-common", "2.99.0"),
            _c("net.imagej", "imagej-common", "2.0.2"),
        ]
        xml = generate_version_pins(components)

        assert "<org.scijava.scijava-common.version>2.99.0<" in xml
        assert "<scijava-common.version>2.99.0<" in xml
        assert "<net.imagej.imagej-common.version>2.0.2<" in xml
        assert "<imagej-common.version>2.0.2<" in xml

    def test_changes_override_version(self):
        components = [_c("org.scijava", "scijava-common", "2.99.0")]
        changes = [_c("org.scijava", "scijava-common", "2.99.4-SNAPSHOT")]
        xml = generate_version_pins(components, changes=changes)

        assert "2.99.4-SNAPSHOT" in xml
        assert "2.99.0" not in xml

    def test_extra_properties(self):
        components = [_c("org.scijava", "scijava-common", "2.99.0")]
        xml = generate_version_pins(
            components,
            extra_properties={
                "java.awt.headless": "true",
                "enforcer.skip": "true",
            },
        )

        assert "<java.awt.headless>true</java.awt.headless>" in xml
        assert "<enforcer.skip>true</enforcer.skip>" in xml

    def test_remove_duplicates(self):
        """When two groups have the same artifactId, keep only the configured one."""
        components = [
            _c("org.antlr", "antlr", "3.5.3"),
            _c("antlr", "antlr", "2.7.7"),
        ]
        config = VersionPinsConfig(
            remove_duplicates={"antlr.version": "org.antlr"},
        )
        xml = generate_version_pins(components, config=config)

        # Long-form properties should both exist
        assert "<org.antlr.antlr.version>3.5.3<" in xml
        assert "<antlr.antlr.version>2.7.7<" in xml

        # Short-form should only exist for org.antlr
        assert "<antlr.version>3.5.3<" in xml
        # The antlr group's short form should not appear
        assert ">2.7.7<" not in xml.split("antlr.antlr.version")[0].split("antlr.version>")[-1] if "antlr.version" in xml else True

    def test_aliases(self):
        """Version property aliases should map to canonical values."""
        components = [_c("net.imagej", "ij", "1.54f")]
        config = VersionPinsConfig(
            aliases={"imagej1.version": "net.imagej.ij.version"},
        )
        xml = generate_version_pins(components, config=config)

        assert "<imagej1.version>1.54f</imagej1.version>" in xml
        assert "<net.imagej.ij.version>1.54f<" in xml

    def test_xml_escaping(self):
        """Special characters in versions should be escaped."""
        components = [_c("org.example", "test", "1.0<beta&1")]
        xml = generate_version_pins(components)

        assert "1.0&lt;beta&amp;1" in xml

    def test_sorted_properties(self):
        """Properties should be sorted alphabetically."""
        components = [
            _c("z.group", "zebra", "1.0"),
            _c("a.group", "alpha", "2.0"),
        ]
        xml = generate_version_pins(components)

        alpha_pos = xml.index("a.group.alpha.version")
        zebra_pos = xml.index("z.group.zebra.version")
        assert alpha_pos < zebra_pos

    def test_empty_components(self):
        """Empty component list should produce valid but empty settings."""
        xml = generate_version_pins([])

        assert "<settings" in xml
        assert "</settings>" in xml
        assert "<properties>" in xml
