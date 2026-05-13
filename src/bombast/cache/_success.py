"""Prior-success tracking for build caching."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bombast.core._component import Component

_log = logging.getLogger(__name__)

DEFAULT_SUCCESS_DIR = Path.home() / ".cache" / "bombast" / "success"


class SuccessCache:
    """Tracks successful builds to avoid redundant retesting.

    Each component's success history is stored as a file containing
    dependency fingerprints (one per line). If the current fingerprint
    matches any cached fingerprint, the build can be skipped.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or DEFAULT_SUCCESS_DIR

    def _cache_path(self, component: Component) -> Path:
        return self.cache_dir / component.group / f"{component.name}.log"

    def has_prior_success(self, component: Component, fp: str) -> bool:
        """Check if a component has been successfully built with this fingerprint.

        Args:
            component: The component to check.
            fp: The dependency fingerprint to look for.

        Returns:
            True if a matching fingerprint is found in the cache.
        """
        cache_file = self._cache_path(component)
        if not cache_file.exists():
            return False

        # Check if fingerprint appears in the cache file.
        try:
            content = cache_file.read_text()
            return fp in content.splitlines()
        except OSError:
            _log.warning("Failed to read success cache: %s", cache_file)
            return False

    def record_success(self, component: Component, fp: str) -> None:
        """Record a successful build for a component.

        Args:
            component: The component that built successfully.
            fp: The dependency fingerprint for this build.
        """
        cache_file = self._cache_path(component)
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        # Prepend the new fingerprint (most recent first).
        existing = ""
        if cache_file.exists():
            existing = cache_file.read_text()

        cache_file.write_text(fp + "\n" + existing)
        _log.debug("Recorded success for %s: %s", component.coordinate, fp)

    def is_snapshot(self, component: Component) -> bool:
        """Check if a component is a SNAPSHOT version (never cached)."""
        return component.version.endswith("-SNAPSHOT")
