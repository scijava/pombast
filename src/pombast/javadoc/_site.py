"""Render the site-wide redirect maps spanning every version in the javadoc tree.

Each run builds one BOM union, but the web server needs a single view of the
whole site, so after every run these maps are regenerated from what is on disk:

* ``redirects.map`` — every union's ``redirects.tsv`` concatenated (named
  unions included): a versioned union path → owning component path. Keys carry
  the BOM version, so unions of different versions never collide.
* ``latest.map`` — ``{g}/{a}`` → newest release version present in the tree, for
  every component and BOM. Backs the floating ``/{g}/{a}/latest/…`` alias.
  SNAPSHOT versions are never "latest".
* ``latest-fallback.map`` — ``/{g}/{a}/latest/{path}`` → ``/{g}/{a}/{v}/{path}``
  for union paths that are absent from the newest union but present in an older
  one (``v`` is the newest such version). Keeps legacy links to since-removed
  classes resolving instead of 404ing.

All three are ``key value`` text, the input format of Apache's ``txt:``
RewriteMap. At full-site scale convert them to DBM (``httxt2dbm``) for the
server — a ``txt:`` map is searched linearly on each cache miss.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import cmp_to_key
from typing import TYPE_CHECKING

from jgo.maven import compare_versions

from pombast.javadoc._fs import atomic_writer
from pombast.javadoc._unpack import _MARKER, has_pages

if TYPE_CHECKING:
    from pathlib import Path

_log = logging.getLogger(__name__)

REDIRECTS_MAP = "redirects.map"
LATEST_MAP = "latest.map"
LATEST_FALLBACK_MAP = "latest-fallback.map"


@dataclass
class SiteMapsResult:
    """Summary of a site-wide map rebuild."""

    redirect_count: int = 0
    latest_count: int = 0
    fallback_count: int = 0
    artifacts: list[Path] = field(default_factory=list)


def build_site_maps(site_dir: Path) -> SiteMapsResult:
    """Regenerate the site-wide redirect maps from the tree under ``site_dir``."""
    result = SiteMapsResult()
    versions = _scan_versions(site_dir)

    # latest.map: g/a -> newest release.
    latest: dict[tuple[str, str], str] = {}
    for ga, vs in versions.items():
        # Only versions with pages to show: never point "latest" at an empty dir.
        releases = [
            v
            for v in vs
            if not v.endswith("-SNAPSHOT")
            and (
                (site_dir / ga[0] / ga[1] / v / "redirects.tsv").is_file()
                or has_pages(site_dir / ga[0] / ga[1] / v)
            )
        ]
        # Prefer real releases over git-hash builds (e.g. JitPack's "9c0918a"),
        # which Maven ordering can rank above any release by a leading digit.
        proper = [v for v in releases if not _is_commit_hash(v)]
        if proper or releases:
            latest[ga] = _newest_first(proper or releases)[0]
    path = site_dir / LATEST_MAP
    with atomic_writer(path) as f:
        for (g, a), v in sorted(latest.items()):
            f.write(f"{g}/{a} {v}\n")
    result.latest_count = len(latest)
    result.artifacts.append(path)

    # The union dirs (BOM versions that have a redirects.tsv), newest first.
    unions: dict[tuple[str, str], list[str]] = {}
    for ga, vs in versions.items():
        built = [
            v for v in vs if (site_dir / ga[0] / ga[1] / v / "redirects.tsv").is_file()
        ]
        if built:
            unions[ga] = _newest_first(built)

    # redirects.map: streamed, since a full multi-version site has millions of rows.
    path = site_dir / REDIRECTS_MAP
    with atomic_writer(path) as f:
        for (g, a), vs in sorted(unions.items()):
            for v in vs:
                for tsv in _union_tsvs(site_dir / g / a / v):
                    for u, c in _read_tsv(tsv):
                        f.write(f"{u} {c}\n")
                        result.redirect_count += 1
    result.artifacts.append(path)

    # latest-fallback.map: paths the latest union dropped, newest older version wins.
    path = site_dir / LATEST_FALLBACK_MAP
    with atomic_writer(path) as f:
        for (g, a), vs in sorted(unions.items()):
            newest = latest.get((g, a))
            if newest is None:
                continue
            seen = _suffixes(site_dir, g, a, newest)
            for v in vs:
                if v == newest or v.endswith("-SNAPSHOT"):
                    continue
                for suffix in sorted(_suffixes(site_dir, g, a, v) - seen):
                    f.write(f"/{g}/{a}/latest/{suffix} /{g}/{a}/{v}/{suffix}\n")
                    result.fallback_count += 1
                    seen.add(suffix)
    result.artifacts.append(path)

    _log.info(
        "Site maps: %d redirects, %d latest versions, %d latest fallbacks",
        result.redirect_count,
        result.latest_count,
        result.fallback_count,
    )
    return result


def _scan_versions(site_dir: Path) -> dict[tuple[str, str], list[str]]:
    """Find every built ``{g}/{a}/{v}`` dir: unpacked components and BOM unions.

    Hidden dirs (unpack staging, swapped-out ``.old`` copies) are ignored.
    """
    found: dict[tuple[str, str], list[str]] = {}
    for gdir in site_dir.iterdir():
        if not gdir.is_dir() or gdir.name.startswith("."):
            continue
        for adir in gdir.iterdir():
            if not adir.is_dir() or adir.name.startswith("."):
                continue
            for vdir in adir.iterdir():
                if vdir.name.startswith(".") or not vdir.is_dir():
                    continue
                if (vdir / _MARKER).exists() or (vdir / "redirects.tsv").is_file():
                    found.setdefault((gdir.name, adir.name), []).append(vdir.name)
    return found


# A bare abbreviated or full git commit hash, as JitPack publishes versions.
_COMMIT_HASH = re.compile(r"[0-9a-f]{7,40}")


def _is_commit_hash(version: str) -> bool:
    # All digits is a date-style version (e.g. 20020414), not a hash.
    return bool(_COMMIT_HASH.fullmatch(version)) and not version.isdigit()


def _newest_first(versions: list[str]) -> list[str]:
    return sorted(versions, key=cmp_to_key(compare_versions), reverse=True)


def _read_tsv(tsv: Path):
    with tsv.open(encoding="utf-8") as f:
        for row in f:
            u, sep, c = row.rstrip("\n").partition("\t")
            if sep:
                yield u, c


def _union_tsvs(vdir: Path) -> list[Path]:
    """A BOM version's redirect tables: its union's, then its named unions'."""
    return [vdir / "redirects.tsv", *sorted(vdir.glob("*/redirects.tsv"))]


def _suffixes(site_dir: Path, g: str, a: str, v: str) -> set[str]:
    """Union paths of one BOM version (named unions included), with the
    ``/{g}/{a}/{v}/`` prefix removed."""
    prefix = f"/{g}/{a}/{v}/"
    return {
        u[len(prefix) :]
        for tsv in _union_tsvs(site_dir / g / a / v)
        for u, _ in _read_tsv(tsv)
        if u.startswith(prefix)
    }
