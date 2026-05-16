"""Main orchestrator for BOM validation."""

from __future__ import annotations

import logging
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pombast.cache._repo import RepoCache
from pombast.cache._success import SuccessCache
from pombast.core._component import (
    BuildResult,
    BuildStatus,
    Component,
    ValidationReport,
)
from pombast.core._filter import ComponentFilter
from pombast.maven._bom import load_bom
from pombast.maven._builder import ComponentSource, MavenComponentBuilder
from pombast.maven._java_version import detect_build_java_version
from pombast.maven._pom_rewriter import patch_pom_urls, rewrite_pom_versions
from pombast.maven._scm import resolve_scm
from pombast.util._git import shallow_clone

if TYPE_CHECKING:
    from pombast.config._settings import PipelineConfig

_log = logging.getLogger(__name__)


class _VersionOverride:
    """Proxy for a jgo dep object that overrides its version attribute."""

    def __init__(self, dep, version: str) -> None:
        self._dep = dep
        self.version = version

    def __getattr__(self, name: str):
        return getattr(self._dep, name)


class Pipeline:
    """Orchestrates the full BOM validation workflow."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    def run(self) -> ValidationReport:
        """Execute the full validation pipeline.

        Steps:
        1. Load BOM and extract managed components
        2. Filter components by include/exclude patterns
        3. Resolve source code for each component
        4. Rewrite POM to hardcode BOM dependency versions
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

        # Apply --change version overrides.
        dep_mgmt = self._apply_changes(bom_data.dep_mgmt)

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

        if self.config.skip_build:
            _log.info("Skip-build mode: stopping after preparation")
            report.end_time = datetime.now(timezone.utc)
            return report

        # Phase 4 + 5: Resolve sources and build/test each component.
        ctx = bom_data.ctx
        repo_cache = RepoCache()
        builder = MavenComponentBuilder(
            output_dir=output_dir,
            all_components=all_components,
            ctx=ctx,
            success_cache=SuccessCache(cache_dir=self.config.success_cache_dir),
            extra_properties=self.config.config.build_properties,
            test_binary=self.config.test_binary,
            changes=self.config.changes or None,
        )

        # Precompute changed G:A set once for prune filtering.
        changed_gas: set[str] = set()
        if self.config.prune and self.config.changes:
            changed_gas = {":".join(c.split(":")[:2]) for c in self.config.changes}

        for component in included:
            # Prune: skip components that don't directly depend on any changed artifact.
            if changed_gas and not self._depends_on_changed(
                component, changed_gas, ctx
            ):
                _log.info(
                    "%s: skipping (pruned — no direct dependency on changed artifacts)",
                    component.coordinate,
                )
                report.results.append(
                    BuildResult(
                        component=component,
                        status=BuildStatus.SKIPPED,
                        skipped_reason="pruned: no dependency on changed artifacts",
                    )
                )
                continue

            # Check if tests should be skipped for this component.
            if component.ga in skip_tests_set:
                _log.info(
                    "%s: skipping (configured in skip-tests)", component.coordinate
                )
                report.results.append(
                    BuildResult(
                        component=component,
                        status=BuildStatus.SKIPPED,
                        skipped_reason="configured skip",
                    )
                )
                continue

            # Resolve SCM info and detect build Java version.
            component = resolve_scm(component, ctx)

            # Check for per-component Java version override from config.
            comp_override = self.config.config.component_overrides.get(component.ga)
            if comp_override and "java-version" in comp_override:
                java_ver = comp_override["java-version"]
                if not isinstance(java_ver, (int, str)):
                    raise ValueError(
                        f"java-version must be int or str, got {type(java_ver).__name__!r}"
                    )
                component = replace(component, java_version=int(java_ver))
            elif component.java_version is None:
                java_version = detect_build_java_version(
                    component, ctx, bom_dep_mgmt=dep_mgmt
                )
                if java_version is not None:
                    component = replace(component, java_version=java_version)

            # Apply minimum Java version floor.
            min_java = self.config.min_java_version
            if min_java is not None:
                current = component.java_version or 0
                if current < min_java:
                    component = replace(component, java_version=min_java)

            if not component.scm_url:
                _log.warning("%s: no SCM URL — skipping", component.coordinate)
                report.results.append(
                    BuildResult(
                        component=component,
                        status=BuildStatus.ERROR,
                        skipped_reason="no SCM URL",
                    )
                )
                continue

            # Clone source.
            source_dir = output_dir / component.group / component.name
            tag = component.scm_tag

            if not tag:
                _log.warning("%s: no SCM tag — skipping", component.coordinate)
                report.results.append(
                    BuildResult(
                        component=component,
                        status=BuildStatus.ERROR,
                        skipped_reason="no SCM tag",
                    )
                )
                continue

            try:
                bare_repo = repo_cache.ensure_ref(component, component.scm_url, tag)
                shallow_clone(bare_repo, tag, source_dir)
            except Exception as e:
                _log.error("%s: clone failed — %s", component.coordinate, e)
                report.results.append(
                    BuildResult(
                        component=component,
                        status=BuildStatus.ERROR,
                        skipped_reason=f"clone failed: {e}",
                    )
                )
                continue

            # Patch and rewrite POM.
            pom_file = source_dir / "pom.xml"
            if pom_file.exists():
                patch_pom_urls(pom_file)
                rewrite_pom_versions(pom_file, dep_mgmt)

            # Build and test.
            source = ComponentSource(component=component, source_dir=source_dir)
            result = builder.build_and_test(source)
            report.results.append(result)

        report.end_time = datetime.now(timezone.utc)
        return report

    def _depends_on_changed(
        self, component: Component, changed_gas: set[str], ctx
    ) -> bool:
        """Return True if component directly depends on any of the given G:A artifacts."""
        from jgo.maven import Model

        try:
            pom = (
                ctx.project(component.group, component.name)
                .at_version(component.version)
                .pom()
            )
            model = Model(pom, ctx, lenient=True)
            for g, a, _c, _t in model.deps:
                if f"{g}:{a}" in changed_gas:
                    return True
        except Exception as e:
            _log.warning(
                "%s: could not check dependencies for pruning — building anyway: %s",
                component.coordinate,
                e,
            )
            return True  # build rather than silently skip on error
        return False

    def _apply_changes(self, dep_mgmt: dict) -> dict:
        """Return a copy of dep_mgmt with --change version overrides applied."""
        if not self.config.changes:
            return dep_mgmt
        result = dict(dep_mgmt)
        for change in self.config.changes:
            parts = change.split(":")
            if len(parts) < 3:
                _log.warning("Invalid change spec (expected G:A:V): %r", change)
                continue
            group_id, artifact_id, version = parts[0], parts[1], ":".join(parts[2:])
            matched = False
            for key in list(result):
                if key[0] == group_id and key[1] == artifact_id:
                    result[key] = _VersionOverride(result[key], version)
                    matched = True
            if not matched:
                _log.warning("Change %r: no matching entry in BOM dep_mgmt", change)
        return result

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
