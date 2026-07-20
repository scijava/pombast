"""Build the BOM-wide unioned javadoc index from unpacked components.

The union directory (``site/{bom.g}/{bom.a}/{bom.v}/``) is a single, reproducible
``javadoc -link`` target for the whole BOM. It contains:

* ``element-list`` / ``package-list`` — the union of every component's package
  index, so the ``javadoc`` tool fetches one small index instead of one per
  dependency (the linear-scaling cost this whole exercise exists to avoid).
* ``redirects.tsv`` — the **canonical, server-agnostic** map from a union path
  to the owning component's real path, one row per class/package page.
* A rendered server config (``.htaccess`` and/or ``redirects.map`` + snippet)
  derived from ``redirects.tsv``.

Actual class HTML is never duplicated into the union — the union only redirects.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pombast.javadoc._unpack import TOPLEVEL_HTML_DOCS, component_javadoc_dir

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.core._component import Component

_log = logging.getLogger(__name__)

# Redirect renderers. "rewritemap" scales (O(1) hashed lookup) but the
# RewriteMap directive must be declared in server/vhost config, not .htaccess.
# "redirectmatch" works in a bare .htaccess but evaluates rules linearly per
# request, so it does not scale to a full BOM — offered as a fallback only.
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
    redirects: list[tuple[str, str]] = []  # (union_path, component_path)
    contributing = 0

    for comp in components:
        cdir = component_javadoc_dir(site_dir, comp)
        if not cdir.is_dir():
            continue
        contributing += 1
        packages.update(_read_packages(cdir))
        redirects.extend(_component_redirects(cdir, bom, comp))

    result = UnionResult(
        union_dir=out,
        package_count=len(packages),
        redirect_count=len(redirects),
        component_count=contributing,
    )

    # element-list and package-list share the same (package-per-line) format.
    index_body = "".join(f"{pkg}\n" for pkg in sorted(packages))
    for name in ("element-list", "package-list"):
        path = out / name
        path.write_text(index_body, encoding="utf-8")
        result.artifacts.append(path)

    # Canonical, server-agnostic redirect table (sorted + de-duped).
    redirects = sorted(set(redirects))
    tsv = out / "redirects.tsv"
    tsv.write_text(
        "".join(f"{u}\t{c}\n" for u, c in redirects), encoding="utf-8"
    )
    result.artifacts.append(tsv)

    result.artifacts.extend(_render_redirects(out, redirects, redirect_format))

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
    """Yield (union_path, component_path) for each class/package page."""
    bom_prefix = f"/{bom.group}/{bom.name}/{bom.version}"
    comp_prefix = f"/{comp.group}/{comp.name}/{comp.version}"
    out: list[tuple[str, str]] = []
    for html in cdir.rglob("*.html"):
        if html.name in TOPLEVEL_HTML_DOCS or not html.is_file():
            continue
        rel = html.relative_to(cdir).as_posix()  # no leading slash — avoids //
        out.append((f"{bom_prefix}/{rel}", f"{comp_prefix}/{rel}"))
    return out


def _render_redirects(
    out: Path, redirects: list[tuple[str, str]], fmt: str
) -> list[Path]:
    """Render server redirect config; return the files written."""
    if fmt == "redirectmatch":
        return _render_redirectmatch(out)  # reads redirects.tsv-derived list
    return _render_rewritemap(out, redirects)


def _render_rewritemap(out: Path, redirects: list[tuple[str, str]]) -> list[Path]:
    """Emit a RewriteMap txt file plus a server-config snippet.

    Apache hashes a ``txt:`` map in memory, giving O(1) lookups regardless of
    catalog size. The ``RewriteMap`` directive is only valid in server/vhost
    context, so we also emit a ready-to-include snippet documenting it.
    """
    map_path = out / "redirects.map"
    map_path.write_text(
        "".join(f"{u} {c}\n" for u, c in redirects), encoding="utf-8"
    )

    conf_path = out / "redirects.conf"
    conf_path.write_text(
        "# Include this in the server/vhost config (RewriteMap is not allowed\n"
        "# inside .htaccess). For very large maps, convert to a DBM at deploy\n"
        "# time with: httxt2dbm -i redirects.map -o redirects.map.db\n"
        f'RewriteMap javadoc "txt:{map_path}"\n'
        "RewriteCond %{REQUEST_URI} ^(/[^/]+/[^/]+/[^/]+/.+)$\n"
        "RewriteRule . ${javadoc:%1} [R=301,L,NE]\n",
        encoding="utf-8",
    )
    return [map_path, conf_path]


def _render_redirectmatch(out: Path) -> list[Path]:
    """Emit a self-contained .htaccess of RedirectMatch rules (does not scale)."""
    lines: list[str] = []
    tsv = out / "redirects.tsv"
    for row in tsv.read_text(encoding="utf-8").splitlines():
        union_path, _, comp_path = row.partition("\t")
        if not comp_path:
            continue
        lines.append(
            f'RedirectMatch permanent "^{re.escape(union_path)}$" {comp_path}\n'
        )
    htaccess = out / ".htaccess"
    htaccess.write_text("".join(lines), encoding="utf-8")
    return [htaccess]
