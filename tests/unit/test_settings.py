"""Tests for configuration loading."""

from pathlib import Path

import pytest

from bombast.config._settings import BombastConfig, PipelineConfig


class TestBombastConfig:
    def test_empty_config(self):
        config = BombastConfig.empty()
        assert config.filter.includes == []
        assert config.filter.excludes == []
        assert config.skip_tests == []
        assert config.remove_tests == {}
        assert config.build_properties == {}

    def test_load_from_toml(self, tmp_path):
        toml_path = tmp_path / "bombast.toml"
        toml_path.write_text("""\
[filter]
includes = ["org.scijava:*", "net.imagej:*"]
excludes = ["net.imagej:ij"]

[skip-tests]
components = ["org.scijava:minimaven"]

[remove-tests]
"net.imagej:imagej-ops" = ["CachedOpEnvironmentTest.java"]

[build.properties]
"java.awt.headless" = "true"
"enforcer.skip" = "true"

[components."sc.fiji:SNT"]
java-version = 17
""")
        config = BombastConfig.load(toml_path)
        assert config.filter.includes == ["org.scijava:*", "net.imagej:*"]
        assert config.filter.excludes == ["net.imagej:ij"]
        assert config.skip_tests == ["org.scijava:minimaven"]
        assert config.remove_tests == {
            "net.imagej:imagej-ops": ["CachedOpEnvironmentTest.java"]
        }
        assert config.build_properties == {
            "java.awt.headless": "true",
            "enforcer.skip": "true",
        }
        assert config.component_overrides == {
            "sc.fiji:SNT": {"java-version": 17},
        }

    def test_load_minimal_toml(self, tmp_path):
        toml_path = tmp_path / "bombast.toml"
        toml_path.write_text("")
        config = BombastConfig.load(toml_path)
        assert config.filter.includes == []
        assert config.skip_tests == []

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            BombastConfig.load(tmp_path / "nonexistent.toml")


class TestPipelineConfig:
    def test_defaults(self):
        config = PipelineConfig(bom="org.scijava:pom-scijava:37.0.0")
        assert config.bom == "org.scijava:pom-scijava:37.0.0"
        assert config.changes == []
        assert config.includes == []
        assert config.excludes == []
        assert config.output_dir == Path("bombast-output")
        assert config.prune is False
        assert config.force is False
        assert config.skip_build is False
        assert config.verbose is False
