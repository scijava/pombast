"""Dependency fingerprinting for build caching."""

from __future__ import annotations

import hashlib

from bombast.core._component import Component


def fingerprint(components: list[Component]) -> str:
    """Compute a content-addressable fingerprint for a set of pinned dependencies.

    The fingerprint is a SHA-256 hash of the sorted G:A:V list. Two builds
    with the same fingerprint have identical dependency configurations and
    need not be retested.

    Args:
        components: The full list of pinned components.

    Returns:
        Hex digest of the fingerprint.
    """
    # Sort by coordinate for deterministic ordering.
    coords = sorted(c.coordinate for c in components)
    content = "\n".join(coords)
    return hashlib.sha256(content.encode()).hexdigest()
