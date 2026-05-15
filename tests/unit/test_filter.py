"""Tests for component filtering."""

from pombast.core import Component, ComponentFilter


def _c(group: str, name: str) -> Component:
    """Shorthand to create a Component for testing."""
    return Component(group=group, name=name, version="1.0")


class TestComponentFilter:
    def test_no_filters_includes_all(self, sample_components):
        f = ComponentFilter()
        assert f.filter(sample_components) == sample_components

    def test_include_single_group(self):
        components = [
            _c("org.scijava", "a"),
            _c("org.scijava", "b"),
            _c("net.imagej", "c"),
        ]
        f = ComponentFilter(includes=["org.scijava:*"])
        result = f.filter(components)
        assert len(result) == 2
        assert all(c.group == "org.scijava" for c in result)

    def test_include_multiple_groups(self):
        components = [
            _c("org.scijava", "a"),
            _c("net.imagej", "b"),
            _c("com.google", "c"),
        ]
        f = ComponentFilter(includes=["org.scijava:*", "net.imagej:*"])
        result = f.filter(components)
        assert len(result) == 2

    def test_exclude_specific_artifact(self):
        components = [
            _c("net.imagej", "imagej-common"),
            _c("net.imagej", "ij"),
        ]
        f = ComponentFilter(excludes=["net.imagej:ij"])
        result = f.filter(components)
        assert len(result) == 1
        assert result[0].name == "imagej-common"

    def test_exclude_overrides_include(self):
        components = [
            _c("org.scijava", "a"),
            _c("org.scijava", "b"),
        ]
        f = ComponentFilter(
            includes=["org.scijava:*"],
            excludes=["org.scijava:b"],
        )
        result = f.filter(components)
        assert len(result) == 1
        assert result[0].name == "a"

    def test_wildcard_group(self):
        components = [
            _c("org.scijava", "a"),
            _c("org.scijava.ops", "b"),
            _c("net.imagej", "c"),
        ]
        f = ComponentFilter(includes=["org.sci*:*"])
        result = f.filter(components)
        assert len(result) == 2

    def test_exact_match(self):
        components = [
            _c("org.scijava", "scijava-common"),
            _c("org.scijava", "scijava-table"),
        ]
        f = ComponentFilter(includes=["org.scijava:scijava-common"])
        result = f.filter(components)
        assert len(result) == 1
        assert result[0].name == "scijava-common"

    def test_empty_result(self):
        components = [_c("org.scijava", "a")]
        f = ComponentFilter(includes=["net.imagej:*"])
        result = f.filter(components)
        assert result == []

    def test_exclude_entire_group(self):
        components = [
            _c("org.openjfx", "javafx-base"),
            _c("org.openjfx", "javafx-controls"),
            _c("org.scijava", "a"),
        ]
        f = ComponentFilter(excludes=["org.openjfx:*"])
        result = f.filter(components)
        assert len(result) == 1
        assert result[0].group == "org.scijava"

    def test_is_included_direct(self):
        f = ComponentFilter(
            includes=["org.scijava:*"],
            excludes=["org.scijava:b"],
        )
        assert f.is_included(_c("org.scijava", "a"))
        assert not f.is_included(_c("org.scijava", "b"))
        assert not f.is_included(_c("net.imagej", "c"))
