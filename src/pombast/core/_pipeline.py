"""Main orchestrator for per-component BOM validation (smelt)."""

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
from pombast.maven._java_version import (
    analyze_build_java,
    floor_from_closure,
    write_dependency_tree_log,
)
from pombast.maven._pom_rewriter import patch_pom_urls, rewrite_pom_versions
from pombast.maven._reactor import locate_module_dir
from pombast.maven._scm import _guess_tag, resolve_scm
from pombast.util._git import shallow_clone

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.config._settings import PipelineConfig

_log = logging.getLogger(__name__)


def remove_test_classes(
    test_root: Path, fqns: list[str], *, warn_missing: bool = True
) -> None:
    """Delete fully-qualified test classes from a ``src/test/java`` root.

    Each fully-qualified name (e.g. ``com.example.FooTest``) maps to the path
    ``com/example/FooTest.java`` beneath ``test_root``. Fully-qualified names
    are required: a bare class name could match identically-named classes in
    unrelated packages, so only the exact path is removed.

    A configured class whose file is absent is logged and skipped rather than
    failing the build. ``warn_missing`` controls the log level: on a fresh
    clone the full source tree is present, so a missing file likely means a
    typo or upstream rename and warrants a warning; on a reused clone the file
    was probably removed on a prior run, so the absence is logged at debug.
    """
    for fqn in fqns:
        target = test_root.joinpath(*fqn.split(".")).with_suffix(".java")
        if target.exists():
            target.unlink()
            _log.info("remove-tests: removed %s", fqn)
        elif warn_missing:
            _log.warning(
                "remove-tests: %s not found at %s — check the configured "
                "fully-qualified class name",
                fqn,
                target,
            )
        else:
            _log.debug("remove-tests: %s already absent at %s", fqn, target)


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
            ctx=ctx,
            success_cache=SuccessCache(cache_dir=self.config.success_cache_dir),
            extra_properties={
                **self.config.config.build_properties,
                **self.config.maven_properties,
            },
            test_binary=self.config.test_binary,
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

            # Resolve SCM info. The build Java version is detected later, after the
            # source is cloned and its POM rewritten, so jgo resolves from the same
            # BOM-pinned POM that Maven will build.
            component = resolve_scm(component, ctx)

            if not component.scm_url:
                # SCM info not available from Maven (e.g. POM not yet on Central).
                # If we have a cached bare repo from a previous run, use its remote
                # URL as a fallback so we can still fetch and clone the new tag.
                fallback_url = repo_cache.get_remote_url(component)
                if fallback_url:
                    _log.info(
                        "%s: SCM URL missing from POM; using cached repo URL: %s",
                        component.coordinate,
                        fallback_url,
                    )
                    guessed_tag = _guess_tag(
                        fallback_url, component.name, component.version
                    )
                    component = replace(
                        component, scm_url=fallback_url, scm_tag=guessed_tag
                    )
                else:
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

            # Check prior-success cache before cloning. A hit means a previously
            # recorded dependency closure for this component still pins to the
            # same versions in the BOM under test — no clone or resolution needed.
            if not builder.success_cache.is_snapshot(component):
                prior_closure = builder.success_cache.matching_closure(
                    component, dep_mgmt
                )
                if prior_closure is not None:
                    _log.info(
                        "%s: skipping — prior success with same pins",
                        component.coordinate,
                    )
                    # Derive bytecode floors from the cached closure (no resolution)
                    # so the status report's Bytecode column is populated even for
                    # components that were not rebuilt this run. Best-effort.
                    cached_analysis = None
                    try:
                        cached_analysis = floor_from_closure(
                            component, ctx, prior_closure
                        )
                    except Exception:
                        _log.debug(
                            "%s: could not derive bytecode from cached closure",
                            component.coordinate,
                        )
                    report.results.append(
                        BuildResult(
                            component=component,
                            status=BuildStatus.SKIPPED,
                            skipped_reason="prior success",
                            analysis=cached_analysis,
                        )
                    )
                    continue

            tag_file = source_dir / ".pombast-tag"
            # Sentinel format: "version:git-tag". Including the component version
            # guards against a stale <scm><tag> in the upstream POM (a common Maven
            # mistake where the developer forgets to update <scm><tag> when releasing),
            # which would otherwise cause pombast to reuse an old clone even after a
            # version bump in the BOM.
            sentinel = f"{component.version}:{tag}"
            fresh_clone = False
            if tag_file.exists() and tag_file.read_text().strip() == sentinel:
                _log.info("%s: reusing existing clone at %s", component.coordinate, tag)
            else:
                if source_dir.exists():
                    _log.info(
                        "%s: tag mismatch or missing sentinel — re-cloning",
                        component.coordinate,
                    )
                    shutil.rmtree(source_dir)
                try:
                    if component.scm_url is None:
                        _log.error("%s: no scm url — %s", component.coordinate)
                        report.results.append(
                            BuildResult(
                                component=component,
                                status=BuildStatus.ERROR,
                                skipped_reason="no scm url",
                            )
                        )
                        continue
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
                fresh_clone = True

            # Locate the module subdirectory that builds this component. For a
            # multi-module project (e.g. BoneJ2, scijava/scijava) the BOM manages
            # each reactor module as its own component; pombast builds in the
            # matching subdirectory and lets sibling modules resolve from the
            # repository as ordinary released dependencies. For a single-module
            # project this is the clone root itself.
            build_dir = locate_module_dir(source_dir, component)
            if build_dir is None:
                _log.warning(
                    "%s: no module POM matched in checkout — using clone root",
                    component.coordinate,
                )
                build_dir = source_dir
            elif build_dir != source_dir:
                _log.info(
                    "%s: building module subdir %s",
                    component.coordinate,
                    build_dir.relative_to(source_dir),
                )

            if fresh_clone:
                # Patch and rewrite POMs only for a fresh clone; re-applying to an
                # already-patched POM would corrupt the pinned versions. Upgrade
                # http→https across every POM in the checkout so inherited
                # repository URLs in parent/aggregator POMs don't break the build,
                # but pin versions only in this module's own POM — its own
                # dependencyManagement takes precedence over anything inherited,
                # so that is sufficient even when the module's parent lies outside
                # the reactor (as with scijava/scijava's pom-scijava-parented
                # modules).
                for pom in source_dir.rglob("pom.xml"):
                    if "target" in pom.relative_to(source_dir).parts:
                        continue
                    patch_pom_urls(pom)
                module_pom = build_dir / "pom.xml"
                if module_pom.exists():
                    rewrite_pom_versions(module_pom, dep_mgmt)

                tag_file.write_text(sentinel + "\n")

            # Remove configured test classes from this component's checkout.
            # Deletion is idempotent, so it runs on every iteration (not just
            # fresh clones) — that way a newly-added remove-tests entry takes
            # effect on a reused clone without forcing a re-clone. Missing files
            # only warn on a fresh clone, when the full source tree is present.
            remove_fqns = self.config.config.remove_tests.get(component.ga, [])
            if remove_fqns:
                remove_test_classes(
                    build_dir / "src" / "test" / "java",
                    remove_fqns,
                    warn_missing=fresh_clone,
                )

            # Determine the build JDK from the rewritten (BOM-pinned) POM, so jgo
            # resolves exactly the dependency set Maven will build. A per-component
            # override wins; otherwise use the detected version, then the default.
            analysis = analyze_build_java(component, ctx, build_dir / "pom.xml")
            comp_override = self.config.config.component_overrides.get(component.ga)
            if comp_override and "java-version" in comp_override:
                java_ver = comp_override["java-version"]
                if not isinstance(java_ver, (int, str)):
                    raise ValueError(
                        f"java-version must be int or str, got {type(java_ver).__name__!r}"
                    )
                component = replace(component, java_version=int(java_ver))
            elif component.java_version is None and analysis.java_version is not None:
                component = replace(component, java_version=analysis.java_version)
            if component.java_version is None and self.config.default_java is not None:
                component = replace(component, java_version=self.config.default_java)

            # Extract per-component Maven property overrides.
            comp_properties: dict[str, str] = {}
            if comp_override and "properties" in comp_override:
                raw = comp_override["properties"]
                if isinstance(raw, dict):
                    comp_properties = {
                        str(k): str(v) if v is not None else "" for k, v in raw.items()
                    }

            # Record the resolved dependency tree (with Java-version rationale) next
            # to the build logs, mirroring mega-melt's dependency-tree.log.
            write_dependency_tree_log(
                analysis, component, build_dir / "dependency-tree.log"
            )

            # Build and test. The resolved closure from Java-version analysis
            # doubles as the success-cache key, so no second resolution is needed.
            source = ComponentSource(
                component=component, source_dir=source_dir, build_dir=build_dir
            )
            result = builder.build_and_test(
                source, closure=analysis.closure, extra_properties=comp_properties
            )
            # Carry the bytecode/closure analysis onto the result so it can be
            # serialized into smelt.json for the status report's Bytecode column.
            result.analysis = analysis
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
        includes = list(self.config.includes) or self.config.config.filter.includes
        excludes = list(self.config.excludes) + self.config.config.filter.excludes
        return ComponentFilter(includes=includes, excludes=excludes)

    def _build_repo_map(self) -> dict[str, str]:
        """Build the remote repository map from config and CLI args."""
        return {"central": "https://repo1.maven.org/maven2", **self.config.repositories}
