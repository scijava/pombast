"""Maven build/test runner for individual components."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from bombast.cache._fingerprint import fingerprint
from bombast.cache._success import SuccessCache
from bombast.core._component import BuildResult, BuildStatus, Component
from bombast.util._process import run_maven

_log = logging.getLogger(__name__)


@dataclass
class ComponentSource:
    """A checked-out source tree for a component."""

    component: Component
    source_dir: Path


class MavenComponentBuilder:
    """Builds and tests individual Maven components with version pins.

    Handles per-component Java version selection, prior-success caching,
    and build log capture.
    """

    def __init__(
        self,
        pins_path: Path,
        output_dir: Path,
        all_components: list[Component],
        success_cache: SuccessCache | None = None,
        extra_properties: dict[str, str] | None = None,
    ) -> None:
        self.pins_path = pins_path
        self.output_dir = output_dir
        self.all_components = all_components
        self.success_cache = success_cache or SuccessCache()
        self.extra_properties = extra_properties or {}
        self._fingerprint = fingerprint(all_components)

    def build_and_test(self, source: ComponentSource) -> BuildResult:
        """Build and test a single component.

        Steps:
        1. Check prior-success cache — skip if unchanged
        2. Detect preferred Java version
        3. Run `mvn clean test` with version pins
        4. Record success/failure

        Args:
            source: The checked-out component source.

        Returns:
            BuildResult with status, log path, and duration.
        """
        component = source.component
        log_path = (
            self.output_dir
            / component.group
            / component.name
            / "build.log"
        )

        # Check prior-success cache.
        if not self.success_cache.is_snapshot(component):
            if self.success_cache.has_prior_success(component, self._fingerprint):
                _log.info("%s: skipping — prior success with same pins", component.coordinate)
                return BuildResult(
                    component=component,
                    status=BuildStatus.SKIPPED,
                    skipped_reason="prior success",
                )

        # Locate Java for this component.
        java_home = self._find_java(component)

        # Run Maven build.
        start = time.monotonic()
        try:
            result = run_maven(
                ["clean", "test"],
                cwd=source.source_dir,
                settings=self.pins_path,
                java_home=java_home,
                extra_properties=self.extra_properties,
                log_path=log_path,
            )
            duration = time.monotonic() - start

            if result.returncode == 0:
                _log.info("%s: SUCCESS (%.1fs)", component.coordinate, duration)
                # Record success.
                self.success_cache.record_success(component, self._fingerprint)
                return BuildResult(
                    component=component,
                    status=BuildStatus.SUCCESS,
                    log_path=log_path,
                    duration_seconds=duration,
                )
            else:
                _log.warning("%s: FAILURE (%.1fs)", component.coordinate, duration)
                return BuildResult(
                    component=component,
                    status=BuildStatus.FAILURE,
                    log_path=log_path,
                    duration_seconds=duration,
                )

        except Exception as e:
            duration = time.monotonic() - start
            _log.error("%s: ERROR — %s", component.coordinate, e)
            return BuildResult(
                component=component,
                status=BuildStatus.ERROR,
                log_path=log_path,
                duration_seconds=duration,
            )

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
            return locator.java_home()
        except Exception:
            _log.warning(
                "%s: failed to locate Java %d; using system default",
                component.coordinate,
                java_version,
            )
            return None
