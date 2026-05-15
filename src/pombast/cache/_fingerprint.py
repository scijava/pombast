"""Dependency fingerprinting for build caching."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pombast.core._component import Component


def fingerprint(components: list[Component], changes: list[str] | None = None) -> str:
    """Compute a content-addressable fingerprint for a set of pinned dependencies.

    The fingerprint is a SHA-256 hash of the sorted G:A:V list, plus any
    explicit version overrides (--change flags).  Two builds with the same
    fingerprint have identical dependency configurations and need not be
    retested.

    Args:
        components: The full list of pinned components.
        changes: Optional list of G:A:V overrides injected via --change.

    Returns:
        Hex digest of the fingerprint.
    """
    # Sort by coordinate for deterministic ordering.
    coords = sorted(c.coordinate for c in components)
    if changes:
        # Prefix with '!' so change entries cannot collide with G:A:V coords.
        coords.extend(f"!{c}" for c in sorted(changes))
    content = "\n".join(coords)
    return hashlib.sha256(content.encode()).hexdigest()
