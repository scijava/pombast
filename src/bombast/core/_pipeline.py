"""Main orchestrator for BOM validation."""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from jgo.maven import MavenContext

from bombast.cache._repo import RepoCache
from bombast.cache._success import SuccessCache
from bombast.config._settings import PipelineConfig
from bombast.maven._java_version import detect_build_java_version
from bombast.core._component import (
    BuildResult,
    BuildStatus,
    Component,
    ValidationReport,
)
from bombast.core._filter import ComponentFilter
from bombast.maven._bom import load_bom
from bombast.maven._builder import ComponentSource, MavenComponentBuilder
from bombast.maven._pins import write_version_pins
from bombast.maven._scm import resolve_scm
from bombast.util._git import shallow_clone

_log = logging.getLogger(__name__)


class Pipeline:
    """Orchestrates the full BOM validation workflow."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(self) -> ValidationReport:
        """Execute the full validation pipeline.

        Steps:
        1. Load BOM and extract managed components
        2. Filter components by include/exclude patterns
        3. Generate version pins (Maven settings.xml)
        4. Resolve source code for each component
        5. Build and test each component
        6. Generate validation report
        """
        report = ValidationReport(
            bom=self.config.bom,
            start_time=datetime.now(timezone.utc),
        )

        # Prepare output directory.
        output_dir = self.config.output_dir
        if output_dir.exists():
            if self.config.force:
                _log.info("Wiping output directory: %s", output_dir)
                shutil.rmtree(output_dir)
            else:
                _log.warning("Output directory exists: %s (use -f to wipe)", output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Phase 1: Load BOM.
        repositories = self._build_repo_map()
        _log.info("Loading BOM: %s", self.config.bom)
        bom_data = load_bom(self.config.bom, repositories=repositories)
        all_components = bom_data.components
        _log.info("Found %d components in BOM", len(all_components))

        # Phase 2: Filter.
        component_filter = self._build_filter()
        included = component_filter.filter(all_components)
        _log.info(
            "After filtering: %d of %d components",
            len(included),
            len(all_components),
        )

        # Apply skip-tests from config.
        skip_tests_set = set(self.config.config.skip_tests)

        # Phase 3: Generate version pins.
        pins_path = output_dir / "version-pins.xml"
        write_version_pins(
            pins_path,
            all_components,
            extra_properties=self.config.config.build_properties,
            config=self.config.config.version_pins,
        )
        _log.info("Wrote version pins to %s", pins_path)

        if self.config.skip_build:
            _log.info("Skip-build mode: stopping after preparation")
            report.end_time = datetime.now(timezone.utc)
            return report

        # Phase 4 + 5: Resolve sources and build/test each component.
        ctx = bom_data.ctx
        repo_cache = RepoCache()
        builder = MavenComponentBuilder(
            pins_path=pins_path,
            output_dir=output_dir,
            all_components=all_components,
            ctx=ctx,
            success_cache=SuccessCache(),
            extra_properties=self.config.config.build_properties,
            test_binary=self.config.test_binary,
        )

        for component in included:
            # Check if tests should be skipped for this component.
            if component.ga in skip_tests_set:
                _log.info("%s: skipping (configured in skip-tests)", component.coordinate)
                report.results.append(BuildResult(
                    component=component,
                    status=BuildStatus.SKIPPED,
                    skipped_reason="configured skip",
                ))
                continue

            # Resolve SCM info and detect build Java version.
            component = resolve_scm(component, ctx)

            # Check for per-component Java version override from config.
            comp_override = self.config.config.component_overrides.get(component.ga)
            if comp_override and "java-version" in comp_override:
                from dataclasses import replace
                component = replace(
                    component, java_version=int(comp_override["java-version"])
                )
            elif component.java_version is None:
                java_version = detect_build_java_version(
                    component, ctx, bom_dep_mgmt=bom_data.dep_mgmt
                )
                if java_version is not None:
                    from dataclasses import replace
                    component = replace(component, java_version=java_version)

            if not component.scm_url:
                _log.warning("%s: no SCM URL — skipping", component.coordinate)
                report.results.append(BuildResult(
                    component=component,
                    status=BuildStatus.ERROR,
                    skipped_reason="no SCM URL",
                ))
                continue

            # Clone source.
            source_dir = output_dir / component.group / component.name
            tag = component.scm_tag

            if not tag:
                _log.warning("%s: no SCM tag — skipping", component.coordinate)
                report.results.append(BuildResult(
                    component=component,
                    status=BuildStatus.ERROR,
                    skipped_reason="no SCM tag",
                ))
                continue

            try:
                bare_repo = repo_cache.ensure_ref(component, component.scm_url, tag)
                shallow_clone(bare_repo, tag, source_dir)
            except Exception as e:
                _log.error("%s: clone failed — %s", component.coordinate, e)
                report.results.append(BuildResult(
                    component=component,
                    status=BuildStatus.ERROR,
                    skipped_reason=f"clone failed: {e}",
                ))
                continue

            # Build and test.
            source = ComponentSource(component=component, source_dir=source_dir)
            result = builder.build_and_test(source)
            report.results.append(result)

        report.end_time = datetime.now(timezone.utc)
        return report

    def _build_filter(self) -> ComponentFilter:
        """Build a ComponentFilter from CLI args and config file."""
        # CLI args take precedence; fall back to config file.
        includes = list(self.config.includes) or self.config.config.filter.includes
        excludes = list(self.config.excludes) + self.config.config.filter.excludes
        return ComponentFilter(includes=includes, excludes=excludes)

    def _build_repo_map(self) -> dict[str, str]:
        """Build the remote repository map from CLI args."""
        repos = {"central": "https://repo1.maven.org/maven2"}
        for i, url in enumerate(self.config.repositories):
            repos[f"repo{i}"] = url
        return repos
