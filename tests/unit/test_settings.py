"""Tests for configuration loading."""

from pathlib import Path

import pytest

from pombast.config._settings import PipelineConfig, PombastConfig


class TestPombastConfig:
    def test_empty_config(self):
        config = PombastConfig.empty()
        assert config.filter.includes == []
        assert config.filter.excludes == []
        assert config.skip_tests == []
        assert config.remove_tests == {}
        assert config.build_properties == {}

    def test_load_from_toml(self, tmp_path):
        toml_path = tmp_path / "pombast.toml"
        toml_path.write_text("""\
[smelt]
includes = ["org.scijava:*", "net.imagej:*"]
excludes = ["net.imagej:ij"]
skip-tests = ["org.scijava:minimaven"]

[remove-tests]
"net.imagej:imagej-ops" = ["CachedOpEnvironmentTest.java"]

[common]
repositories = ["https://maven.scijava.org/content/groups/public"]

[common.properties]
"java.awt.headless" = "true"
"enforcer.skip" = "true"

[components."sc.fiji:SNT"]
java-version = 17
""")
        config = PombastConfig.load(toml_path)
        assert config.filter.includes == ["org.scijava:*", "net.imagej:*"]
        assert config.filter.excludes == ["net.imagej:ij"]
        assert config.skip_tests == ["org.scijava:minimaven"]
        assert config.remove_tests == {
            "net.imagej:imagej-ops": ["CachedOpEnvironmentTest.java"]
        }
        assert config.repositories == {
            "repo0": "https://maven.scijava.org/content/groups/public"
        }
        assert config.build_properties == {
            "java.awt.headless": "true",
            "enforcer.skip": "true",
        }
        assert config.component_overrides == {
            "sc.fiji:SNT": {"java-version": 17},
        }

    def test_load_minimal_toml(self, tmp_path):
        toml_path = tmp_path / "pombast.toml"
        toml_path.write_text("")
        config = PombastConfig.load(toml_path)
        assert config.filter.includes == []
        assert config.skip_tests == []

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PombastConfig.load(tmp_path / "nonexistent.toml")


class TestLoadDefault:
    def test_explicit_path_takes_precedence(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        auto = tmp_path / "pombast.toml"
        auto.write_text('[smelt]\nincludes = ["auto:*"]\n')
        explicit = tmp_path / "other.toml"
        explicit.write_text('[smelt]\nincludes = ["explicit:*"]\n')
        config = PombastConfig.load_default(explicit)
        assert config.filter.includes == ["explicit:*"]

    def test_auto_discovers_pombast_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pombast.toml").write_text('[smelt]\nincludes = ["auto:*"]\n')
        config = PombastConfig.load_default(None)
        assert config.filter.includes == ["auto:*"]

    def test_falls_back_to_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = PombastConfig.load_default(None)
        assert config.filter.includes == []
        assert config.skip_tests == []


class TestStatusConfig:
    def test_defaults(self):
        config = PombastConfig.empty()
        assert config.status.rules is None
        assert config.status.output is None

    def test_load_status_section(self, tmp_path):
        (tmp_path / "rules.xml").write_text("<rules/>")
        (tmp_path / "projects.txt").write_text("")
        (tmp_path / "timestamps.txt").write_text("")
        (tmp_path / "header.html").write_text("")
        (tmp_path / "footer.html").write_text("")
        toml_path = tmp_path / "pombast.toml"
        toml_path.write_text("""\
[status]
rules = "rules.xml"
projects = "projects.txt"
timestamps = "timestamps.txt"
smelt = "smelt.json"
output = "index.html"
header = "header.html"
footer = "footer.html"
""")
        config = PombastConfig.load(toml_path)
        assert config.status.rules == (tmp_path / "rules.xml").resolve()
        assert config.status.projects == (tmp_path / "projects.txt").resolve()
        assert config.status.timestamps == (tmp_path / "timestamps.txt").resolve()
        assert config.status.smelt == (tmp_path / "smelt.json").resolve()
        assert config.status.output == (tmp_path / "index.html").resolve()
        assert config.status.header == (tmp_path / "header.html").resolve()
        assert config.status.footer == (tmp_path / "footer.html").resolve()


class TestOutputPaths:
    """Output-artifact path config for smelt, badges, and team."""

    def test_defaults_none(self):
        config = PombastConfig.empty()
        assert config.smelt_output is None
        assert config.badges.output is None
        assert config.team.output is None

    def test_load_output_paths(self, tmp_path):
        toml_path = tmp_path / "pombast.toml"
        toml_path.write_text("""\
[smelt]
output = "out/smelt.json"

[badges]
output = "out/badges.json"

[team]
output = "out/team.html"
""")
        config = PombastConfig.load(toml_path)
        assert config.smelt_output == (tmp_path / "out/smelt.json").resolve()
        assert config.badges.output == (tmp_path / "out/badges.json").resolve()
        assert config.team.output == (tmp_path / "out/team.html").resolve()


class TestMegaMeltConfig:
    def test_defaults(self):
        config = PombastConfig.empty()
        assert config.mega_melt.java_version is None
        assert config.mega_melt.template is None
        assert config.mega_melt.filter.includes == []
        assert config.mega_melt.filter.excludes == []

    def test_load_mega_melt_section(self, tmp_path):
        template = tmp_path / "template.xml"
        template.write_text("<project/>")
        toml_path = tmp_path / "pombast.toml"
        toml_path.write_text("""\
[melt]
java-version = 11
template = "template.xml"
includes = ["org.foo:*"]
excludes = ["org.foo:bad"]
""")
        config = PombastConfig.load(toml_path)
        assert config.mega_melt.java_version == 11
        assert config.mega_melt.template == template.resolve()
        assert config.mega_melt.filter.includes == ["org.foo:*"]
        assert config.mega_melt.filter.excludes == ["org.foo:bad"]

    def test_load_mega_melt_defaults_when_absent(self, tmp_path):
        toml_path = tmp_path / "pombast.toml"
        toml_path.write_text("")
        config = PombastConfig.load(toml_path)
        assert config.mega_melt.java_version is None
        assert config.mega_melt.template is None


class TestJavadocConfig:
    def test_defaults(self):
        jc = PombastConfig.empty().javadoc
        assert jc.url_prefix == ""
        assert jc.redirect_format == "rewritemap"
        assert jc.workers == 8
        assert jc.jdk_api_url_template == "/Java{java}/"
        assert jc.jdk_api_base_urls == {}

    def test_load_jdk_settings(self, tmp_path):
        toml_path = tmp_path / "pombast.toml"
        toml_path.write_text("""\
[javadoc]
url-prefix = "https://javadoc.scijava.org"
jdk-api-url-template = "/JDK{java}/"

[javadoc.jdk-api-base-urls]
j8 = "https://docs.oracle.com/javase/8/docs/api/"
j21 = "https://docs.oracle.com/en/java/javase/21/docs/api/"
""")
        jc = PombastConfig.load(toml_path).javadoc
        assert jc.url_prefix == "https://javadoc.scijava.org"
        assert jc.jdk_api_url_template == "/JDK{java}/"
        assert jc.jdk_api_base_urls == {
            "j8": "https://docs.oracle.com/javase/8/docs/api/",
            "j21": "https://docs.oracle.com/en/java/javase/21/docs/api/",
        }


class TestPipelineConfig:
    def test_defaults(self):
        config = PipelineConfig(bom="org.scijava:pom-scijava:37.0.0")
        assert config.bom == "org.scijava:pom-scijava:37.0.0"
        assert config.changes == []
        assert config.includes == []
        assert config.excludes == []
        assert config.output_dir == Path("target") / "pombast"
        assert config.prune is False
        assert config.force is False
        assert config.skip_build is False
        assert config.verbose is False
