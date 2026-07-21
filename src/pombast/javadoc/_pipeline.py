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
from pombast.javadoc._crosslink import (
    ClassIndexer,
    CrosslinkResult,
    CrosslinkStatus,
    crosslink_component,
)
from pombast.javadoc._deps import Closure, resolve_closure
from pombast.javadoc._union import UnionResult, build_union
from pombast.javadoc._unpack import UnpackResult, UnpackStatus, unpack_component
from pombast.maven._bom import load_bom

if TYPE_CHECKING:
    from pathlib import Path

_log = logging.getLogger(__name__)

# Progress callbacks, invoked as each unit of a phase completes.
UnpackCb = Callable[[UnpackResult], None]
CrosslinkCb = Callable[[CrosslinkResult], None]
ResolveCb = Callable[[Component], None]


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
    jdk_api_url_template: str = "/Java{java}/"
    jdk_api_base_urls: dict[str, str] = field(default_factory=dict)


@dataclass
class JavadocReport:
    """Aggregate outcome of a javadoc run."""

    bom: Component
    results: list[UnpackResult] = field(default_factory=list)
    crosslinks: list[CrosslinkResult] = field(default_factory=list)
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

    @property
    def crosslinked(self) -> list[CrosslinkResult]:
        return [c for c in self.crosslinks if c.status == CrosslinkStatus.CROSSLINKED]

    @property
    def links_rewritten(self) -> int:
        return sum(c.links_rewritten for c in self.crosslinks)


class JavadocPipeline:
    """Generate a browsable javadoc site + unioned index for a BOM."""

    def __init__(self, config: JavadocRunConfig):
        self.config = config

    def run(
        self,
        *,
        on_resolve: ResolveCb | None = None,
        on_unpack: UnpackCb | None = None,
        on_crosslink: CrosslinkCb | None = None,
    ) -> JavadocReport:
        cfg = self.config
        repos = dict(cfg.repositories)
        repos.setdefault("central", "https://repo1.maven.org/maven2")

        bom_data = load_bom(cfg.bom, repositories=repos)
        bom = _bom_component(cfg.bom, bom_data.pom_path)
        ctx = bom_data.ctx

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
        workers = max(1, cfg.workers)

        # Phase 0: resolve each managed component's actual dependency closure and
        # target Java version. These versions (not the BOM's managed ones, nor the
        # javadoc's stale baked-in JDK prefix) are what crosslinking targets.
        closures: dict[str, Closure] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            resolve_futures = {
                pool.submit(resolve_closure, ctx, comp): comp for comp in components
            }
            for future in as_completed(resolve_futures):
                comp = resolve_futures[future]
                closures[comp.coordinate] = future.result()
                if on_resolve is not None:
                    on_resolve(comp)

        # Unpack set = managed components ∪ every resolved dependency, so link
        # targets actually exist in the tree. Deduplicated by G:A:V.
        unpack_targets: dict[str, Component] = {c.coordinate: c for c in components}
        for closure in closures.values():
            for dep in closure.deps:
                unpack_targets.setdefault(dep.coordinate, dep)

        # Phase 1: download + unpack + adjust every target (parallel, cached).
        with ThreadPoolExecutor(max_workers=workers) as pool:
            unpack_futures = [
                pool.submit(
                    unpack_component,
                    ctx,
                    comp,
                    site,
                    url_prefix=cfg.url_prefix,
                    force=cfg.force,
                )
                for comp in unpack_targets.values()
            ]
            for uf in as_completed(unpack_futures):
                unpack_result = uf.result()
                report.results.append(unpack_result)
                if on_unpack is not None:
                    on_unpack(unpack_result)

        # Phase 2: crosslink each managed component against its own closure.
        indexer = ClassIndexer(site)
        empty_closure = Closure()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            crosslink_futures = [
                pool.submit(
                    crosslink_component,
                    site,
                    comp,
                    closures.get(comp.coordinate, empty_closure).deps,
                    indexer,
                    url_prefix=cfg.url_prefix,
                    java_version=closures.get(
                        comp.coordinate, empty_closure
                    ).java_version,
                    jdk_template=cfg.jdk_api_url_template,
                    jdk_base_urls=cfg.jdk_api_base_urls,
                    force=cfg.force,
                )
                for comp in components
            ]
            for xf in as_completed(crosslink_futures):
                xlink_result = xf.result()
                report.crosslinks.append(xlink_result)
                if on_crosslink is not None:
                    on_crosslink(xlink_result)

        # Phase 3: build the BOM-wide union from whatever unpacked successfully.
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
