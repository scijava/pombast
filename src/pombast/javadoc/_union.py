"""Build the BOM-wide unioned javadoc index from unpacked components.

The union directory (``site/{bom.g}/{bom.a}/{bom.v}/``) is a single, reproducible
``javadoc -link`` target for the whole BOM. It contains:

* ``element-list`` / ``package-list`` — the union of every component's package
  index, so the ``javadoc`` tool fetches one small index instead of one per
  dependency (the linear-scaling cost this whole exercise exists to avoid).
* ``redirects.tsv`` — the **canonical, server-agnostic** map from a union path
  to the owning component's real path, one row per class/package page.
* ``index.html`` — a landing page listing the contributing components.
* Optionally (``redirectmatch`` format) a self-contained ``.htaccess``. The
  scalable ``rewritemap`` format is rendered site-wide instead, across every
  union in the tree (see :mod:`pombast.javadoc._site`).

Union paths are keyed by the *non-modular* class path (``ij/ImagePlus.html``),
matching the flat ``element-list`` the union publishes — which is what a
``javadoc -link`` consumer (and any legacy link) will request. The redirect
target keeps the component's real, possibly module-nested, location
(``ij/ij/ImagePlus.html``).

Actual class HTML is never duplicated into the union — the union only redirects.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pombast.javadoc._crosslink import _module_names
from pombast.javadoc._fs import atomic_write_text
from pombast.javadoc._unpack import TOPLEVEL_HTML_DOCS, component_javadoc_dir

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.core._component import Component

_log = logging.getLogger(__name__)

# Top-level directories of generated javadoc whose pages are artifact-wide
# scaffolding (they would collide across components), not per-class/package.
_SKIP_DIRS = frozenset({"index-files", "legal", "resources", "script-dir"})

# Redirect renderers. "rewritemap" scales (hashed DBM lookup, rendered site-wide
# by pombast.javadoc._site) but the RewriteMap directive must be declared in
# server/vhost config, not .htaccess. "redirectmatch" works in a bare .htaccess
# but evaluates rules linearly per request, so it does not scale to a full BOM —
# offered as a fallback only.
REDIRECT_FORMATS = ("rewritemap", "redirectmatch")


@dataclass
class UnionResult:
    """Summary of a BOM union build."""

    union_dir: Path
    package_count: int = 0
    redirect_count: int = 0
    component_count: int = 0
    artifacts: list[Path] = field(default_factory=list)


def union_dir(site_dir: Path, bom: Component) -> Path:
    """Return the BOM union directory: ``site/{g}/{a}/{v}``."""
    return site_dir / bom.group / bom.name / bom.version


def build_union(
    site_dir: Path,
    bom: Component,
    components: list[Component],
    *,
    redirect_format: str = "rewritemap",
) -> UnionResult:
    """Assemble the unioned index + redirect layer for ``bom``.

    Only components whose javadoc was actually unpacked (i.e. their directory
    exists) contribute; missing ones are silently skipped.
    """
    if redirect_format not in REDIRECT_FORMATS:
        raise ValueError(
            f"Unknown redirect_format {redirect_format!r}; "
            f"expected one of {REDIRECT_FORMATS}"
        )

    out = union_dir(site_dir, bom)
    out.mkdir(parents=True, exist_ok=True)

    packages: set[str] = set()
    # union_path -> component_path. A path two components share (e.g. the
    # package-summary.html of a split package) goes to the first component in
    # BOM order, so the result is deterministic.
    redirects: dict[str, str] = {}
    contributing: list[Component] = []

    for comp in components:
        cdir = component_javadoc_dir(site_dir, comp)
        if not cdir.is_dir():
            continue
        contributing.append(comp)
        packages.update(_read_packages(cdir))
        for u, c in _component_redirects(cdir, bom, comp):
            redirects.setdefault(u, c)

    result = UnionResult(
        union_dir=out,
        package_count=len(packages),
        redirect_count=len(redirects),
        component_count=len(contributing),
    )

    # element-list and package-list share the same (package-per-line) format.
    index_body = "".join(f"{pkg}\n" for pkg in sorted(packages))
    for name in ("element-list", "package-list"):
        path = out / name
        atomic_write_text(path, index_body)
        result.artifacts.append(path)

    # Canonical, server-agnostic redirect table (sorted by union path).
    rows = sorted(redirects.items())
    tsv = out / "redirects.tsv"
    atomic_write_text(tsv, "".join(f"{u}\t{c}\n" for u, c in rows))
    result.artifacts.append(tsv)

    landing = out / "index.html"
    atomic_write_text(landing, _landing_page(bom, contributing))
    result.artifacts.append(landing)

    if redirect_format == "redirectmatch":
        result.artifacts.append(_render_redirectmatch(out, rows))

    # Per-union RewriteMap files from earlier pombast versions are superseded by
    # the site-wide maps; drop any stale copies so they are not published.
    for stale in ("redirects.map", "redirects.conf"):
        (out / stale).unlink(missing_ok=True)

    _log.info(
        "Union %s: %d packages, %d redirects from %d components",
        bom.coordinate,
        result.package_count,
        result.redirect_count,
        result.component_count,
    )
    return result


def _read_packages(cdir: Path) -> set[str]:
    """Read a component's package names from element-list (or package-list).

    ``module:`` lines emitted by modular (JPMS) javadoc are dropped so the
    unioned index stays a valid non-modular package list that the ``javadoc``
    tool accepts as a ``-link`` target across a mix of modular and legacy JARs.
    """
    for name in ("element-list", "package-list"):
        index = cdir / name
        if not index.exists():
            continue
        packages: set[str] = set()
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("module:"):
                continue
            packages.add(line)
        return packages
    return set()


def _component_redirects(
    cdir: Path, bom: Component, comp: Component
) -> list[tuple[str, str]]:
    """Yield (union_path, component_path) for each class/package page.

    For modular javadoc the leading ``{module}/`` segment is dropped from the
    union path only (see module docstring). Artifact-wide pages — top-level
    index/overview documents, module summaries, the split index — are skipped,
    since each component has its own and they would collide in the union.
    """
    bom_prefix = f"/{bom.group}/{bom.name}/{bom.version}"
    comp_prefix = f"/{comp.group}/{comp.name}/{comp.version}"
    modules = _module_names(cdir)
    out: list[tuple[str, str]] = []
    for page in cdir.rglob("*.html"):
        if not page.is_file():
            continue
        rel = page.relative_to(cdir).as_posix()  # no leading slash — avoids //
        parts = rel.split("/")
        if modules and len(parts) > 1 and parts[0] in modules:
            parts = parts[1:]
        if parts[0] in _SKIP_DIRS:
            continue
        if len(parts) == 1 and (
            parts[0] in TOPLEVEL_HTML_DOCS or parts[0].startswith("module-")
        ):
            continue
        out.append((f"{bom_prefix}/{'/'.join(parts)}", f"{comp_prefix}/{rel}"))
    return out


def _landing_page(bom: Component, components: list[Component]) -> str:
    """Render the union's ``index.html``: links to each contributing component."""
    items = "".join(
        f'<li><a href="../../../{html.escape(c.group)}/{html.escape(c.name)}/'
        f'{html.escape(c.version)}/">{html.escape(c.coordinate)}</a></li>\n'
        for c in sorted(components, key=lambda c: (c.group, c.name))
    )
    title = html.escape(bom.coordinate)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{title} javadoc</title>\n</head>\n<body>\n"
        f"<h1>{title}</h1>\n"
        f"<p>Javadoc for the {len(components)} components managed by this BOM.</p>\n"
        f"<ul>\n{items}</ul>\n</body>\n</html>\n"
    )


def _render_redirectmatch(out: Path, rows: list[tuple[str, str]]) -> Path:
    """Emit a self-contained .htaccess of RedirectMatch rules (does not scale)."""
    htaccess = out / ".htaccess"
    atomic_write_text(
        htaccess,
        "".join(f'RedirectMatch permanent "^{re.escape(u)}$" {c}\n' for u, c in rows),
    )
    return htaccess
