"""Orchestrate javadoc site generation for a BOM.

Compose across BOM versions *externally* (one BOM per run); component extraction
is cached per G:A:V so re-running for another BOM version re-uses already
unpacked release javadoc rather than redoing the work.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from pombast.core._component import Component
from pombast.core._filter import ComponentFilter
from pombast.javadoc._union import UnionResult, build_union
from pombast.javadoc._unpack import UnpackResult, UnpackStatus, unpack_component
from pombast.maven._bom import load_bom

if TYPE_CHECKING:
    from pathlib import Path

_log = logging.getLogger(__name__)

# Progress callback: (component, result) after each unpack completes.
ProgressCb = Callable[[UnpackResult], None]


@dataclass
class JavadocRunConfig:
    """Resolved inputs for a single javadoc site-generation run.

    Built by the CLI from flags overlaid on the ``[javadoc]`` config section
    (see :class:`pombast.config._settings.JavadocConfig`).
    """

    bom: str
    output_dir: Path
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    repositories: dict[str, str] = field(default_factory=dict)
    url_prefix: str = ""
    redirect_format: str = "rewritemap"
    workers: int = 8
    force: bool = False


@dataclass
class JavadocReport:
    """Aggregate outcome of a javadoc run."""

    bom: Component
    results: list[UnpackResult] = field(default_factory=list)
    union: UnionResult | None = None

    def _by(self, status: UnpackStatus) -> list[UnpackResult]:
        return [r for r in self.results if r.status == status]

    @property
    def unpacked(self) -> list[UnpackResult]:
        return self._by(UnpackStatus.UNPACKED)

    @property
    def cached(self) -> list[UnpackResult]:
        return self._by(UnpackStatus.CACHED)

    @property
    def missing(self) -> list[UnpackResult]:
        return self._by(UnpackStatus.MISSING)

    @property
    def errors(self) -> list[UnpackResult]:
        return self._by(UnpackStatus.ERROR)


class JavadocPipeline:
    """Generate a browsable javadoc site + unioned index for a BOM."""

    def __init__(self, config: JavadocRunConfig):
        self.config = config

    def run(self, progress: ProgressCb | None = None) -> JavadocReport:
        cfg = self.config
        repos = dict(cfg.repositories)
        repos.setdefault("central", "https://repo1.maven.org/maven2")

        bom_data = load_bom(cfg.bom, repositories=repos)
        bom = _bom_component(cfg.bom, bom_data.pom_path)

        cf = ComponentFilter(includes=cfg.includes, excludes=cfg.excludes)
        components = cf.filter(bom_data.components)
        _log.info(
            "Generating javadoc for %d of %d components",
            len(components),
            len(bom_data.components),
        )

        site = cfg.output_dir
        site.mkdir(parents=True, exist_ok=True)

        report = JavadocReport(bom=bom)

        # Phase 1: download + unpack + adjust each component (parallel, cached).
        with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as pool:
            futures = {
                pool.submit(
                    unpack_component,
                    bom_data.ctx,
                    comp,
                    site,
                    url_prefix=cfg.url_prefix,
                    force=cfg.force,
                ): comp
                for comp in components
            }
            for future in as_completed(futures):
                result = future.result()
                report.results.append(result)
                if progress is not None:
                    progress(result)

        # Phase 2: build the BOM-wide union from whatever unpacked successfully.
        report.union = build_union(
            site,
            bom,
            components,
            redirect_format=cfg.redirect_format,
        )
        return report


def _bom_component(bom: str, pom_path: Path) -> Component:
    """Derive a Component (G:A:V) identity for the BOM itself.

    For a remote coordinate this is just the parsed G:A:V. For a local BOM
    directory we fall back to reading coordinates from its pom.xml.
    """
    if ":" in bom:
        g, a, v = bom.split(":")[:3]
        return Component(group=g, name=a, version=v)

    from jgo.maven import POM

    pom = POM(pom_path)
    # groupId/version may be inherited from the parent in a local BOM POM.
    g = pom.groupId or pom.value("parent/groupId") or ""
    a = pom.artifactId or ""
    v = pom.version or pom.value("parent/version") or ""
    return Component(group=g, name=a, version=v)
