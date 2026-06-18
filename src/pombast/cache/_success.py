"""Prior-success tracking for build caching.

A component's success history is stored as a file of *dependency closures* — one
per line, each line a sorted, comma-joined list of ``g:a:c:t:v`` (GACT plus
version) entries describing the fully resolved dependency set of one successful
build.

The check path avoids dependency re-resolution by revalidating each stored
closure against the *current* BOM pins: a closure is a cache hit if every
dependency it recorded still pins to the same version in the BOM under test
(``dep_mgmt``). Because which other components are being smelted has no bearing
on a given component's own closure, this is both correct and cheap — no clone,
no dependency resolution, just a GACT lookup per entry.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pombast.core._component import Component

_log = logging.getLogger(__name__)

DEFAULT_SUCCESS_DIR = Path.home() / ".cache" / "pombast" / "success"


def closure_matches_pins(closure: list[str], dep_mgmt: dict) -> bool:
    """Return True if a recorded closure still agrees with the current BOM pins.

    For each recorded ``g:a:c:t:v`` entry, the artifact's current BOM-managed
    version is looked up by its ``(group, artifact, classifier, type)`` key:

    - A SNAPSHOT pin forces a rebuild (never a hit).
    - A version that has drifted from the recorded one means the closure no
      longer describes this build — not a hit.
    - An unmanaged (unpinned) dependency cannot be validated without resolving,
      so it is ignored.

    A closure with no drifted or snapshotted entry is a hit. A malformed entry
    (e.g. a line written by an older cache format) makes the whole closure a
    non-match, so it is harmlessly superseded the next time the build succeeds.
    """
    for entry in closure:
        parsed = _parse_entry(entry)
        if parsed is None:
            return False
        group, artifact, classifier, type_pkg, version = parsed
        pinned = dep_mgmt.get((group, artifact, classifier, type_pkg))
        if pinned is None or not pinned.version:
            continue  # Unmanaged / version-less entry — can't validate; ignore.
        pinned_version = pinned.version
        if pinned_version.endswith("-SNAPSHOT"):
            return False  # Snapshot pin — force a rebuild.
        if pinned_version != version:
            return False  # A pinned dependency changed since this success.
    return True


def _parse_entry(entry: str) -> tuple[str, str, str, str, str] | None:
    """Split a ``g:a:c:t:v`` closure entry into its five fields.

    Coordinates never contain colons (groupIds are dot-separated; classifier,
    type, and version are simple tokens), so a plain split is unambiguous; an
    empty classifier appears as an empty field. Returns None for an entry that
    does not have exactly five fields (e.g. a legacy fingerprint line).
    """
    parts = entry.split(":")
    if len(parts) != 5:
        return None
    group, artifact, classifier, type_pkg, version = parts
    return group, artifact, classifier, type_pkg, version


class SuccessCache:
    """Tracks successful builds, keyed by each component's dependency closure.

    Each component's success history is stored as a file of closures (one per
    line). If any stored closure still matches the current BOM pins, the build
    can be skipped.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or DEFAULT_SUCCESS_DIR

    def _cache_path(self, component: Component) -> Path:
        return self.cache_dir / component.group / f"{component.name}.log"

    @staticmethod
    def _self_entry(component: Component) -> str:
        """The component's own ``g:a:c:t:v`` entry for the success-cache key.

        The cache file is keyed only by ``group/name`` (version-free), and a
        component's own version never appears among its *dependencies* — so
        without this, a bump of the component's own version in the BOM (with
        unchanged or no dependencies) would still hit the cache and skip a
        never-tested build. Recording the component itself as a closure entry
        routes its version through the same pin-revalidation used for
        dependencies: a self-version drift in the BOM invalidates the success.

        The entry has an empty classifier and uses the component's
        ``primary_type`` — i.e. the ``<type>`` under which the BOM manages the
        component's primary artifact (``jar``, ``bundle``, ``maven-plugin``) —
        so it reconstructs the exact ``dependencyManagement`` key the component
        was extracted from, rather than assuming jar.
        """
        return (
            f"{component.group}:{component.name}::{component.primary_type}:"
            f"{component.version}"
        )

    @staticmethod
    def _is_self_entry(entry: str, component: Component) -> bool:
        """True if a closure entry refers to the component's own G:A."""
        parts = entry.split(":")
        return len(parts) == 5 and (parts[0], parts[1]) == (
            component.group,
            component.name,
        )

    def has_prior_success(self, component: Component, dep_mgmt: dict) -> bool:
        """Check if any prior success still agrees with the current BOM pins.

        Args:
            component: The component to check.
            dep_mgmt: The BOM dependency management under test, keyed by
                ``(group, artifact, classifier, type)`` → dependency.

        Returns:
            True if a stored closure matches the current pins (a cache hit).
        """
        return self.matching_closure(component, dep_mgmt) is not None

    def matching_closure(
        self, component: Component, dep_mgmt: dict
    ) -> list[str] | None:
        """Return the stored closure that still agrees with the current BOM pins.

        Args:
            component: The component to check.
            dep_mgmt: The BOM dependency management under test, keyed by
                ``(group, artifact, classifier, type)`` → dependency.

        Returns:
            The matching closure as a list of ``g:a:c:t:v`` entries (a cache hit),
            or None if no stored closure matches.
        """
        cache_file = self._cache_path(component)
        if not cache_file.exists():
            return None

        try:
            lines = cache_file.read_text().splitlines()
        except OSError:
            _log.warning("Failed to read success cache: %s", cache_file)
            return None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            entries = line.split(",")
            # A line lacking the component's own self-entry predates
            # self-versioning; ignore it so the component rebuilds once and
            # re-records in the current format (its own version then guarded).
            if not any(self._is_self_entry(e, component) for e in entries):
                continue
            if closure_matches_pins(entries, dep_mgmt):
                # Strip the component's own self-entry before returning, so the
                # caller sees a pure dependency closure (the self-entry exists
                # only to make the component's own version part of the key).
                return [e for e in entries if not self._is_self_entry(e, component)]
        return None

    def record_success(self, component: Component, closure: list[str]) -> None:
        """Record a successful build's resolved dependency closure.

        The component's own ``g:a:c:t:v`` entry is folded into the recorded
        closure (see :meth:`_self_entry`) so its version is part of the key;
        this also means the key is never empty, even for a component with no
        dependencies. The closure is stored as a single sorted, comma-joined
        line and *prepended* (most recent first), since the latest
        configuration is the one most likely to recur. No-ops on an exact
        duplicate of an existing line, or when the closure contains a SNAPSHOT
        (which could never cleanly match the pins on a later run).

        Args:
            component: The component that built successfully.
            closure: The resolved dependency set as ``g:a:c:t:v`` entries.
        """
        line = ",".join(sorted([self._self_entry(component), *closure]))
        if "-SNAPSHOT" in line:
            return

        cache_file = self._cache_path(component)
        existing = ""
        if cache_file.exists():
            existing = cache_file.read_text()
            if line in existing.splitlines():
                return  # Already recorded this exact closure.

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(line + "\n" + existing)
        _log.debug(
            "Recorded success for %s (%d deps)", component.coordinate, len(closure)
        )

    def is_snapshot(self, component: Component) -> bool:
        """Check if a component is a SNAPSHOT version (never cached)."""
        return component.version.endswith("-SNAPSHOT")
