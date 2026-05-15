"""Maven build/test runner for individual components."""

from __future__ import annotations

import logging
import time
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pombast.cache._fingerprint import fingerprint
from pombast.cache._success import SuccessCache
from pombast.core._component import BuildResult, BuildStatus, Component
from pombast.util._process import run_maven

if TYPE_CHECKING:
    from pathlib import Path

    from jgo.maven import MavenContext

_log = logging.getLogger(__name__)


@dataclass
class ComponentSource:
    """A checked-out source tree for a component."""

    component: Component
    source_dir: Path


class MavenComponentBuilder:
    """Builds and tests individual Maven components.

    Handles per-component Java version selection, prior-success caching,
    and build log capture.  Optionally runs a binary-compatibility test
    before the full source rebuild.
    """

    def __init__(
        self,
        output_dir: Path,
        all_components: list[Component],
        ctx: MavenContext,
        success_cache: SuccessCache | None = None,
        extra_properties: dict[str, str] | None = None,
        test_binary: bool = True,
        changes: list[str] | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.all_components = all_components
        self.ctx = ctx
        self.success_cache = success_cache or SuccessCache()
        self.extra_properties = extra_properties or {}
        self.test_binary = test_binary
        self._fingerprint = fingerprint(all_components, changes)

    def build_and_test(self, source: ComponentSource) -> BuildResult:
        """Build and test a single component.

        Steps:
        1. Check prior-success cache — skip if unchanged
        2. Locate appropriate JDK
        3. (Optional) Test deployed binary against pinned deps
        4. Rebuild from source with pinned deps
        5. Record success/failure

        Args:
            source: The checked-out component source.

        Returns:
            BuildResult with status, log path, and duration.
        """
        component = source.component
        log_dir = self.output_dir / component.group / component.name

        # Check prior-success cache.
        if not self.success_cache.is_snapshot(component):
            if self.success_cache.has_prior_success(component, self._fingerprint):
                _log.info(
                    "%s: skipping — prior success with same pins", component.coordinate
                )
                return BuildResult(
                    component=component,
                    status=BuildStatus.SKIPPED,
                    skipped_reason="prior success",
                )

        # Locate Java for this component.
        java_home = self._find_java(component)

        # Phase 1: Binary compatibility test (optional).
        binary_status = None
        binary_log_path = None
        if self.test_binary:
            binary_status, binary_log_path = self._test_binary(
                source, java_home, log_dir
            )

        # Phase 2: Rebuild from source.
        source_log_path = log_dir / "source-build.log"
        start = time.monotonic()
        try:
            result = run_maven(
                ["clean", "test"],
                cwd=source.source_dir,
                java_home=java_home,
                extra_properties=self.extra_properties,
                log_path=source_log_path,
            )
            duration = time.monotonic() - start

            if result.returncode == 0:
                _log.info(
                    "%s: source build SUCCESS (%.1fs)", component.coordinate, duration
                )
                self.success_cache.record_success(component, self._fingerprint)
                return BuildResult(
                    component=component,
                    status=BuildStatus.SUCCESS,
                    log_path=source_log_path,
                    duration_seconds=duration,
                    binary_status=binary_status,
                    binary_log_path=binary_log_path,
                )
            else:
                _log.warning(
                    "%s: source build FAILURE (%.1fs)", component.coordinate, duration
                )
                return BuildResult(
                    component=component,
                    status=BuildStatus.FAILURE,
                    log_path=source_log_path,
                    duration_seconds=duration,
                    binary_status=binary_status,
                    binary_log_path=binary_log_path,
                )

        except Exception as e:
            duration = time.monotonic() - start
            _log.error("%s: source build ERROR — %s", component.coordinate, e)
            return BuildResult(
                component=component,
                status=BuildStatus.ERROR,
                log_path=source_log_path,
                duration_seconds=duration,
                binary_status=binary_status,
                binary_log_path=binary_log_path,
            )

    def _test_binary(
        self,
        source: ComponentSource,
        java_home: Path | None,
        log_dir: Path,
    ) -> tuple[BuildStatus | None, Path | None]:
        """Test the deployed binary against BOM-pinned dependencies.

        Downloads the released JAR via dependency:get, unpacks it into
        target/classes, then runs tests without recompiling main sources.
        This validates that the published bytecode is compatible with
        the dependency versions from the BOM being tested.

        Returns:
            (binary_status, binary_log_path) tuple.
        """
        component = source.component
        gav = component.coordinate
        log_path = log_dir / "binary-test.log"

        _log.info("%s: testing deployed binary", component.coordinate)

        try:
            # Step 1: Resolve the released JAR via jgo (downloads if needed).
            jar_path = self._resolve_jar(component)
            if jar_path is None or not jar_path.exists():
                _log.warning("%s: JAR not found — skipping binary test", gav)
                return (BuildStatus.SKIPPED, None)

            # Step 3: Unpack JAR into target/classes.
            classes_dir = source.source_dir / "target" / "classes"
            classes_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(jar_path, "r") as zf:
                zf.extractall(classes_dir)

            # Step 4: Run tests against the deployed binary.
            # -Dmaven.main.skip=true skips main source compilation
            # -Dmaven.resources.skip=true skips resource processing
            test_result = run_maven(
                ["test"],
                cwd=source.source_dir,
                java_home=java_home,
                extra_properties={
                    **self.extra_properties,
                    "maven.main.skip": "true",
                    "maven.resources.skip": "true",
                },
                log_path=log_path,
            )

            if test_result.returncode == 0:
                _log.info("%s: binary test SUCCESS", gav)
                return (BuildStatus.SUCCESS, log_path)
            else:
                _log.warning("%s: binary test FAILURE", gav)
                return (BuildStatus.FAILURE, log_path)

        except Exception as e:
            _log.error("%s: binary test ERROR — %s", gav, e)
            return (BuildStatus.ERROR, log_path)

    def _resolve_jar(self, component: Component) -> Path | None:
        """Resolve a component's JAR via jgo, downloading if needed."""
        try:
            maven_component = self.ctx.project(
                component.group, component.name
            ).at_version(component.version)
            return maven_component.artifact().resolve()
        except Exception as e:
            _log.warning("%s: failed to resolve JAR — %s", component.coordinate, e)
            return None

    def _find_java(self, component: Component) -> Path | None:
        """Find the appropriate Java installation for a component.

        Uses jgo's JavaLocator to find or download the right JDK version.

        Returns:
            Path to JAVA_HOME, or None to use system default.
        """
        java_version = component.java_version
        if java_version is None:
            return None

        try:
            from jgo.util.java import JavaLocator, JavaSource

            locator = JavaLocator(
                java_version=java_version,
                java_source=JavaSource.AUTO,
            )
            # locate() returns Path to java executable (e.g. .../bin/java).
            # We need JAVA_HOME, which is the parent of the bin/ directory.
            java_exe = locator.locate()
            return java_exe.parent.parent
        except Exception:
            _log.warning(
                "%s: failed to locate Java %d; using system default",
                component.coordinate,
                java_version,
            )
            return None
