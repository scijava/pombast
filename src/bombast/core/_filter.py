"""Component filtering by include/exclude patterns."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._component import Component


@dataclass
class ComponentFilter:
    """Determines which components enter the melt based on glob patterns.

    Patterns are matched against the G:A string (e.g., "org.scijava:*").
    If includes is non-empty, a component must match at least one include pattern.
    A component matching any exclude pattern is always excluded.
    """

    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)

    def is_included(self, component: Component) -> bool:
        """Return True if the component passes the include/exclude filters."""
        ga = component.ga

        # If excludes match, always reject.
        if any(self._matches(ga, pattern) for pattern in self.excludes):
            return False

        # If no includes specified, accept everything not excluded.
        if not self.includes:
            return True

        # Must match at least one include pattern.
        return any(self._matches(ga, pattern) for pattern in self.includes)

    def filter(self, components: list[Component]) -> list[Component]:
        """Return only the components that pass the filter."""
        return [c for c in components if self.is_included(c)]

    @staticmethod
    def _matches(ga: str, pattern: str) -> bool:
        """Match a G:A string against a glob pattern.

        Supports patterns like:
        - "org.scijava:*" — all artifacts in org.scijava
        - "org.scijava:scijava-common" — exact match
        - "*:scijava-common" — artifact in any group
        - "org.sci*:*" — groups starting with org.sci
        """
        return fnmatch(ga, pattern)
