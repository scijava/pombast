"""Download, unpack, and adjust the javadoc JAR of a single component.

This step is deliberately **BOM-independent**: the output for a given G:A:V is
identical no matter which BOM referenced it, so it can be cached and shared
across BOM versions. Re-extraction is skipped when a completion marker is
present (see ``_MARKER``).
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

from jgo.maven import RepositoryAccessDenied

from pombast.javadoc._fs import atomic_write_text, swap_dir

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
    GENERATED = "generated"  # built from the -sources JAR (no -javadoc JAR)
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

    # A marked dir without pages is an empty stub unpacked before stubs were
    # recognized; re-examine it so its javadoc can be generated instead.
    if marker.exists() and not force and has_pages(javadoc_dir):
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
    except RepositoryAccessDenied:
        raise
    except Exception as e:  # jgo raises RuntimeError when it cannot resolve
        _log.info("No javadoc artifact for %s (%s)", comp.coordinate, e)
        return UnpackResult(comp, UnpackStatus.MISSING, error=str(e))

    if not _has_html(jar):
        # Some projects publish an empty stub -javadoc JAR (only to satisfy
        # Maven Central's rules); report it missing so the sources are used.
        if javadoc_dir.exists():
            shutil.rmtree(javadoc_dir)
        _log.info("Empty javadoc JAR for %s", comp.coordinate)
        return UnpackResult(comp, UnpackStatus.MISSING, error="javadoc JAR has no HTML")

    # Unpack into a sibling staging dir and swap it into place only once
    # complete, so a (possibly hard-linked, published) existing dir is never
    # overwritten file by file.
    staged = javadoc_dir.with_name(f".{javadoc_dir.name}.staging")
    try:
        if staged.exists():
            shutil.rmtree(staged)
        _extract(jar, staged)
        _adjust_legacy_links(staged, url_prefix)
        (staged / _MARKER).write_text("")
        swap_dir(staged, javadoc_dir)
    except (BadZipFile, OSError) as e:
        shutil.rmtree(staged, ignore_errors=True)
        _log.warning("Failed to unpack javadoc for %s: %s", comp.coordinate, e)
        return UnpackResult(comp, UnpackStatus.ERROR, javadoc_dir, error=str(e))

    _log.info("Unpacked javadoc for %s", comp.coordinate)
    return UnpackResult(comp, UnpackStatus.UNPACKED, javadoc_dir)


def has_pages(javadoc_dir: Path) -> bool:
    """Whether a javadoc dir has any HTML page (some nest theirs in a subdir)."""
    if (javadoc_dir / "index.html").exists():
        return True
    return next(javadoc_dir.rglob("*.html"), None) is not None


def _has_html(jar: Path) -> bool:
    """Whether the JAR contains any HTML page (i.e. is not an empty stub)."""
    try:
        with ZipFile(jar) as z:
            return any(n.endswith(".html") for n in z.namelist())
    except (BadZipFile, OSError):
        return True  # let extraction report the problem


def _extract(jar: Path, dest: Path) -> None:
    """Extract a javadoc JAR into ``dest`` (created if needed)."""
    dest.mkdir(parents=True, exist_ok=True)
    with ZipFile(jar) as z:
        _dedupe_central_directory(z)
        z.extractall(dest)


def _dedupe_central_directory(z: ZipFile) -> None:
    """Drop central-directory entries that repeat an earlier entry's local header.

    Some javadoc JARs (e.g. ASM 5.0.x) list every entry twice, both pointing at
    the same local header. That is harmless, but Python 3.12+'s zip-bomb check
    bounds each entry by the next entry's header offset, so the duplicate gets a
    zero-length bound and extraction fails with "Overlapped entries". Keeping
    one entry per offset and recomputing those bounds as zipfile itself does
    restores a normal archive; genuinely overlapping data is still rejected.
    """
    seen: set[int] = set()
    unique = []
    for info in z.filelist:
        if info.header_offset not in seen:
            seen.add(info.header_offset)
            unique.append(info)
    if len(unique) == len(z.filelist):
        return
    z.filelist[:] = unique
    z.NameToInfo = {info.filename: info for info in unique}
    end_offset = z.start_dir  # type: ignore[attr-defined]
    for info in sorted(unique, key=lambda i: i.header_offset, reverse=True):
        info._end_offset = end_offset  # type: ignore[attr-defined]
        end_offset = info.header_offset


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
            atomic_write_text(html, new_text, errors="surrogateescape")
