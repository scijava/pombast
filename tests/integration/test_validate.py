"""Integration tests for the validate subcommand using the minibom fixture.

These tests run real Maven builds and therefore populate ~/.m2, ~/.cache/jgo,
and ~/.cache/cjdk caches.  They are intentionally slow.
"""

from __future__ import annotations

import re
from pathlib import Path

from pombast.config._settings import PipelineConfig
from pombast.core._component import BuildStatus
from pombast.core._pipeline import Pipeline

MINIBOM = Path(__file__).parent.parent / "fixtures" / "minibom"

# Components from the minibom (4 total), in same order as the BOM.
_APP_LAUNCHER = "org.scijava:app-launcher:2.3.1"
_PARSINGTON = "org.scijava:parsington:3.1.0"
_SJ_COMMON = "org.scijava:scijava-common:2.99.2"
_SJ_DESKTOP = "org.scijava:scijava-desktop:1.0.0"

_ALL_COMPONENTS = [_APP_LAUNCHER, _PARSINGTON, _SJ_COMMON, _SJ_DESKTOP]

# parsington 1.0.0 predates the 3.x API that scijava-common 2.99.2 uses,
# so injecting it should cause a compilation failure.
_PARSINGTON_INCOMPATIBLE = "org.scijava:parsington:1.0.0"


def _make_pipeline(tmp_path: Path, **kwargs) -> Pipeline:
    config = PipelineConfig(
        bom=str(MINIBOM),
        output_dir=tmp_path / "output",
        success_cache_dir=tmp_path / ".success-cache",
        test_binary=False,
        force=True,
        **kwargs,
    )
    return Pipeline(config)


def _make_pipeline_with_config(tmp_path: Path, config_path: Path, **kwargs) -> Pipeline:
    """Create a pipeline with a config file."""
    from pombast.config._settings import PombastConfig

    pombast_config = PombastConfig.load(config_path)

    pipeline_config = PipelineConfig(
        bom=str(MINIBOM),
        output_dir=tmp_path / "output",
        success_cache_dir=tmp_path / ".success-cache",
        test_binary=False,
        force=True,
        config=pombast_config,
        **kwargs,
    )
    return Pipeline(pipeline_config)


def _assert_components(report, expected: list[str]) -> None:
    """Assert the report contains exactly the given component coordinates, in order."""
    actual = [r.component.coordinate for r in report.results]
    assert actual == expected, f"expected {expected}, but found: {actual}"


class TestValidate:
    def test_passing_bom(self, tmp_path):
        """scijava-common should build successfully against the minibom."""
        pipeline = _make_pipeline(tmp_path, includes=["org.scijava:scijava-common"])
        report = pipeline.run()

        _assert_components(report, [_SJ_COMMON])
        failures = [r for r in report.results if r.status != BuildStatus.SUCCESS]
        assert not failures, (
            f"unexpected failures: {[r.component.coordinate for r in failures]}"
        )

    def test_incompatible_parsington(self, tmp_path):
        """Injecting parsington 1.0.0 via -c should cause scijava-common to fail."""
        pipeline = _make_pipeline(
            tmp_path,
            includes=["org.scijava:scijava-common"],
            changes=[_PARSINGTON_INCOMPATIBLE],
        )
        report = pipeline.run()

        _assert_components(report, [_SJ_COMMON])
        failures = [
            r
            for r in report.results
            if r.status in (BuildStatus.FAILURE, BuildStatus.ERROR)
        ]
        assert failures, (
            "expected validation failure when building scijava-common against "
            f"parsington 1.0.0, but got: {[r.status for r in report.results]}"
        )

        all_logs = []
        for failure in failures:
            try:
                log_content = Path(failure.log_path).read_text(encoding="utf-8")
                all_logs.append(log_content)
            except Exception as e:
                print(f"Warning: Could not read failure log at {failure.log_path}: {e}")

        log_content_to_check = "\n\n".join(all_logs)

        expected_incompatibility_regex = r"package org\.scijava\.parsington does not exist|cannot find symbol class Token|cannot find symbol class DefaultTreeEvaluator"

        assert re.search(
            expected_incompatibility_regex, log_content_to_check, re.IGNORECASE
        ), (
            f"expected compilation failure matching signature {expected_incompatibility_regex}, "
            f"but found unexpected build log content."
        )

    def test_exclude_component(self, tmp_path):
        """Excluding a component via -e should skip it entirely."""
        pipeline = _make_pipeline(tmp_path, excludes=["org.scijava:scijava-common"])
        report = pipeline.run()

        _assert_components(report, [_APP_LAUNCHER, _PARSINGTON, _SJ_DESKTOP])

    def test_exclude_nonexistent(self, tmp_path):
        """Excluding a non-existent component should not affect results."""
        pipeline = _make_pipeline(tmp_path, excludes=["org.nonexistent:nonexistent"])
        report = pipeline.run()

        _assert_components(report, _ALL_COMPONENTS)

    def test_prune_with_change(self, tmp_path):
        """With prune, only components that depend on the change should be built."""
        pipeline = _make_pipeline(
            tmp_path,
            changes=[_PARSINGTON_INCOMPATIBLE],
            prune=True,
        )
        report = pipeline.run()

        _assert_components(report, _ALL_COMPONENTS)
        built = [r for r in report.results if r.status != BuildStatus.SKIPPED]
        skipped = [r for r in report.results if r.status == BuildStatus.SKIPPED]
        assert [r.component.coordinate for r in built] == [_SJ_COMMON], (
            f"expected only scijava-common to be built with prune, "
            f"but built: {[r.component.coordinate for r in built]}"
        )
        assert [r.component.coordinate for r in skipped] == [
            _APP_LAUNCHER,
            _PARSINGTON,
            _SJ_DESKTOP,
        ], (
            f"expected app-launcher, parsington, scijava-desktop to be skipped with prune, "
            f"but skipped: {[r.component.coordinate for r in skipped]}"
        )

    def test_exclude_and_include_interaction(self, tmp_path):
        """When both -i and -e are used, exclude takes precedence for matching components."""
        pipeline = _make_pipeline(
            tmp_path,
            includes=["org.scijava:scijava-*"],
            excludes=["org.scijava:scijava-common"],
        )
        report = pipeline.run()

        # "org.scijava:scijava-*" matches scijava-common and scijava-desktop;
        # scijava-common is then excluded, leaving only scijava-desktop.
        _assert_components(report, [_SJ_DESKTOP])

    def test_repository_option(self, tmp_path):
        """Adding a repository via -r should be accepted without error."""
        pipeline = _make_pipeline(
            tmp_path,
            includes=["org.scijava:scijava-common"],
            repositories=["https://repo1.maven.org/maven2"],
        )
        report = pipeline.run()

        _assert_components(report, [_SJ_COMMON])

    def test_multiple_repositories(self, tmp_path):
        """Multiple -r options should all be added to the repository map."""
        pipeline = _make_pipeline(
            tmp_path,
            includes=["org.scijava:scijava-common"],
            repositories=[
                "https://repo1.maven.org/maven2",
                "https://repo.jfrog.org/artifactory",
            ],
        )
        report = pipeline.run()

        _assert_components(report, [_SJ_COMMON])

    def test_skip_build_option(self, tmp_path):
        """Using -s should skip actual builds; no results are produced."""
        pipeline = _make_pipeline(
            tmp_path,
            includes=["org.scijava:scijava-common"],
            skip_build=True,
        )
        report = pipeline.run()

        _assert_components(report, [])

    def test_config_file_loading(self, tmp_path):
        """Loading configuration from a pombast.toml file should work."""
        config_path = MINIBOM / "pombast.toml"

        pipeline = _make_pipeline_with_config(tmp_path, config_path)
        report = pipeline.run()

        _assert_components(report, _ALL_COMPONENTS)

    def test_config_min_java_version(self, tmp_path):
        """Config file min-java-version should be used if not specified on CLI."""
        config_path = MINIBOM / "pombast.toml"

        pipeline = _make_pipeline_with_config(tmp_path, config_path)
        report = pipeline.run()

        _assert_components(report, _ALL_COMPONENTS)
