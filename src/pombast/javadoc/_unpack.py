"""Download, unpack, and adjust the javadoc JAR of a single component.

This step is deliberately **BOM-independent**: the output for a given G:A:V is
identical no matter which BOM referenced it, so it can be cached and shared
across BOM versions. Re-extraction is skipped when a completion marker is
present (see ``_MARKER``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

if TYPE_CHECKING:
    from pathlib import Path

    from jgo.maven import MavenContext

    from pombast.core._component import Component

_log = logging.getLogger(__name__)

# Marker written into a component's javadoc dir once fully unpacked+adjusted.
# Its presence means "don't redo this"; its absence (even with a populated dir)
# means a prior run died partway and we should re-extract.
_MARKER = ".pombast-unpacked"

# Toplevel javadoc documents that describe the whole artifact rather than a
# specific class or package. These are intentionally NOT redirected by the BOM
# union (each component has its own), so the union layer skips them.
TOPLEVEL_HTML_DOCS = frozenset(
    {
        "about.html",
        "allclasses-frame.html",
        "allclasses-index.html",
        "allclasses-noframe.html",
        "allclasses.html",
        "allpackages-index.html",
        "constant-values.html",
        "deprecated-list.html",
        "help-doc.html",
        "index-all.html",
        "index.html",
        "overview-frame.html",
        "overview-summary.html",
        "overview-tree.html",
        "package-frame.html",
        "package-summary.html",
        "package-tree.html",
        "package-use.html",
        "serialized-form.html",
    }
)

# Legacy javadoc.scijava.org / javadoc.imagej.net absolute links baked into old
# javadoc HTML. We strip the scheme+host so they become site-relative (or
# prefixed with a configured URL prefix). NOTE: the old flat path segment that
# follows (e.g. "/SciJava/") is preserved as-is; mapping those legacy prefixes
# onto the new /G/A/V/ layout is a deployment-level redirect concern and is
# intentionally deferred (see README "later iteration").
_LEGACY_LINK = re.compile(r"https?://javadoc\.(?:scijava\.org|imagej\.net)")


class UnpackStatus(Enum):
    """Outcome of unpacking one component's javadoc."""

    UNPACKED = "unpacked"  # freshly extracted this run
    CACHED = "cached"  # already present, skipped
    MISSING = "missing"  # no -javadoc artifact published
    ERROR = "error"  # download/extract failed


@dataclass
class UnpackResult:
    """Result of unpacking a single component's javadoc JAR."""

    component: Component
    status: UnpackStatus
    javadoc_dir: Path | None = None
    error: str | None = None


def component_javadoc_dir(site_dir: Path, comp: Component) -> Path:
    """Return the per-component javadoc directory: ``site/{g}/{a}/{v}``."""
    return site_dir / comp.group / comp.name / comp.version


def unpack_component(
    ctx: MavenContext,
    comp: Component,
    site_dir: Path,
    *,
    url_prefix: str = "",
    force: bool = False,
) -> UnpackResult:
    """Resolve, extract, and adjust one component's ``-javadoc`` JAR.

    Args:
        ctx: jgo Maven context (handles download + local caching of the JAR).
        comp: The component whose javadoc to unpack.
        site_dir: Root of the javadoc site tree.
        url_prefix: Optional absolute prefix (e.g. ``https://javadoc.scijava.org``)
            substituted for legacy javadoc host links; empty ⇒ site-relative.
        force: Re-extract even if a completion marker is present.

    Returns:
        An :class:`UnpackResult` describing what happened.
    """
    javadoc_dir = component_javadoc_dir(site_dir, comp)
    marker = javadoc_dir / _MARKER

    if marker.exists() and not force:
        _log.debug("Cached javadoc for %s", comp.coordinate)
        return UnpackResult(comp, UnpackStatus.CACHED, javadoc_dir)

    # Resolve the -javadoc classifier JAR via jgo (downloads + caches as needed).
    try:
        jar = (
            ctx.project(comp.group, comp.name)
            .at_version(comp.version)
            .artifact(classifier="javadoc", packaging="jar")
            .resolve()
        )
    except Exception as e:  # jgo raises RuntimeError when it cannot resolve
        _log.info("No javadoc artifact for %s (%s)", comp.coordinate, e)
        return UnpackResult(comp, UnpackStatus.MISSING, error=str(e))

    try:
        _extract(jar, javadoc_dir)
        _adjust_legacy_links(javadoc_dir, url_prefix)
    except (BadZipFile, OSError) as e:
        _log.warning("Failed to unpack javadoc for %s: %s", comp.coordinate, e)
        return UnpackResult(comp, UnpackStatus.ERROR, javadoc_dir, error=str(e))

    marker.write_text("")
    _log.info("Unpacked javadoc for %s", comp.coordinate)
    return UnpackResult(comp, UnpackStatus.UNPACKED, javadoc_dir)


def _extract(jar: Path, dest: Path) -> None:
    """Extract a javadoc JAR into ``dest`` (created if needed)."""
    dest.mkdir(parents=True, exist_ok=True)
    with ZipFile(jar) as z:
        z.extractall(dest)


def _adjust_legacy_links(javadoc_dir: Path, url_prefix: str) -> None:
    """Rewrite legacy absolute javadoc host links inside extracted HTML."""
    replacement = url_prefix.rstrip("/")
    for html in javadoc_dir.rglob("*.html"):
        if not html.is_file():
            continue
        try:
            text = html.read_text(encoding="utf-8", errors="surrogateescape")
        except OSError as e:
            _log.debug("Skipping unreadable %s: %s", html, e)
            continue
        new_text, n = _LEGACY_LINK.subn(replacement, text)
        if n:
            html.write_text(new_text, encoding="utf-8", errors="surrogateescape")
