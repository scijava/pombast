"""Locate the module subdirectory that builds a given component.

A multi-module Maven project is one checkout that produces several published
artifacts, each managed separately in a BOM. pombast clones such a repo per
component (the clones are cheap and independent) and builds, tests, and pins
each component *in its own module subdirectory* rather than from the reactor
root. Sibling modules resolve from the repository as ordinary released
dependencies, so no whole-reactor build is required. This module maps a
component's G:A coordinate to the directory whose POM builds it.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.core._component import Component

_log = logging.getLogger(__name__)

# Maven POM namespace.
_NS = "http://maven.apache.org/POM/4.0.0"


def _pom_ga(pom_path: Path) -> tuple[str, str] | None:
    """Return the effective (groupId, artifactId) declared by a POM.

    The groupId is frequently inherited rather than declared, so fall back to
    ``<parent><groupId>`` when the module omits its own — true for every
    pom-scijava-parented module (groupId ``org.scijava`` comes from the parent).
    Returns None if the file cannot be parsed or lacks an artifactId.
    """
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return None

    artifact = root.find(f"{{{_NS}}}artifactId")
    if artifact is None or not artifact.text:
        return None

    group = root.find(f"{{{_NS}}}groupId")
    if group is None or not group.text:
        parent = root.find(f"{{{_NS}}}parent")
        if parent is not None:
            group = parent.find(f"{{{_NS}}}groupId")
    if group is None or not group.text:
        return None

    return group.text.strip(), artifact.text.strip()


def locate_module_dir(repo_root: Path, component: Component) -> Path | None:
    """Return the directory whose POM builds ``component``'s artifact.

    Scans every ``pom.xml`` in the checkout (skipping build output under
    ``target/``), matching on the effective groupId:artifactId. For a
    single-module project this is the repo root itself, which is checked first
    so the common case short-circuits. Returns None when no POM matches, leaving
    the caller to fall back to the repo root.
    """
    target = (component.group, component.name)

    root_pom = repo_root / "pom.xml"
    if root_pom.exists() and _pom_ga(root_pom) == target:
        return repo_root

    for pom in sorted(repo_root.rglob("pom.xml")):
        if "target" in pom.relative_to(repo_root).parts:
            continue
        if _pom_ga(pom) == target:
            return pom.parent

    return None
