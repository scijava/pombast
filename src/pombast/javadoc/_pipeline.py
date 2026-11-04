"""Orchestrate javadoc site generation for a BOM.

Compose across BOM versions *externally* (one BOM per run); component extraction
is cached per G:A:V so re-running for another BOM version re-uses already
unpacked release javadoc rather than redoing the work.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pombast.core._component import Component
from pombast.core._filter import ComponentFilter
from pombast.javadoc._crosslink import (
    ClassIndexer,
    CrosslinkResult,
    CrosslinkStatus,
    JdkModuleResolver,
    crosslink_component,
)
from pombast.javadoc._deps import Closure, resolve_closure
from pombast.javadoc._generate import generate_component
from pombast.javadoc._site import SiteMapsResult, build_site_maps
from pombast.javadoc._union import UnionResult, build_union
from pombast.javadoc._unpack import UnpackResult, UnpackStatus, unpack_component
from pombast.maven._bom import load_bom

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_log = logging.getLogger(__name__)

# Progress callbacks, invoked as each unit of a phase completes.
UnpackCb = Callable[[UnpackResult], None]
CrosslinkCb = Callable[[CrosslinkResult], None]
# on_resolve(component, top_level, top_level_total): top_level is True for the
# managed components (the first wave), False for dependencies discovered deeper
# in the recursive closure. top_level_total is len(managed components), so the
# resolve bar can show top-level progress even though the grand total (managed +
# full transitive closure) is unknowable until resolution reaches its fixpoint.
ResolveCb = Callable[[Component, bool, int], None]
# on_plan(total): fired once resolution reaches its fixpoint, carrying the final
# count of components to unpack/crosslink. Lets those (determinate) phases show a
# real M/N bar with an ETA.
PlanCb = Callable[[int], None]


def _remove_stale_unions(union_dir: Path, names: set[str]) -> None:
    """Delete named unions of this BOM version that are no longer configured."""
    for tsv in union_dir.glob("*/redirects.tsv"):
        if tsv.parent.name not in names:
            _log.info("Removing unconfigured union %s", tsv.parent.name)
            shutil.rmtree(tsv.parent)


@contextmanager
def _pool(workers: int) -> Iterator[ThreadPoolExecutor]:
    """A thread pool that drops its queued tasks if the caller fails.

    A plain ``with ThreadPoolExecutor()`` runs every queued task before
    re-raising; after a repository refusal (403) each would make its own
    doomed request, so cancel them instead.
    """
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        yield pool
    except BaseException:
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)


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
    unions: dict[str, list[str]] = field(default_factory=dict)
    extras: list[str] = field(default_factory=list)


@dataclass
class JavadocReport:
    """Aggregate outcome of a javadoc run."""

    bom: Component
    results: list[UnpackResult] = field(default_factory=list)
    crosslinks: list[CrosslinkResult] = field(default_factory=list)
    union: UnionResult | None = None
    named_unions: dict[str, UnionResult] = field(default_factory=dict)
    site_maps: SiteMapsResult | None = None

    def _by(self, status: UnpackStatus) -> list[UnpackResult]:
        return [r for r in self.results if r.status == status]

    @property
    def unpacked(self) -> list[UnpackResult]:
        return self._by(UnpackStatus.UNPACKED)

    @property
    def cached(self) -> list[UnpackResult]:
        return self._by(UnpackStatus.CACHED)

    @property
    def generated(self) -> list[UnpackResult]:
        return self._by(UnpackStatus.GENERATED)

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
        on_plan: PlanCb | None = None,
        on_unpack: UnpackCb | None = None,
        on_crosslink: CrosslinkCb | None = None,
    ) -> JavadocReport:
        cfg = self.config
        repos = dict(cfg.repositories)
        repos.setdefault("central", "https://repo1.maven.org/maven2")

        # Javadoc belongs to a G:A:V whatever its classifiers, so a G:A the BOM
        # manages only with one (e.g. JavaFX's platform JARs) is included too.
        bom_data = load_bom(cfg.bom, repositories=repos, classified_only=True)
        bom = _bom_component(cfg.bom, bom_data.pom_path)
        ctx = bom_data.ctx

        cf = ComponentFilter(includes=cfg.includes, excludes=cfg.excludes)
        components = cf.filter(bom_data.components)
        _log.info(
            "Generating javadoc for %d of %d components",
            len(components),
            len(bom_data.components),
        )

        # Extras are published beside the BOM's components, but are not part
        # of the BOM, so they join no union.
        managed = {c.coordinate for c in components}
        extras = [
            e
            for e in dict.fromkeys(Component.parse(x) for x in cfg.extras)
            if e.coordinate not in managed
        ]
        if extras:
            _log.info("Also generating javadoc for %d extras", len(extras))

        site = cfg.output_dir
        site.mkdir(parents=True, exist_ok=True)

        report = JavadocReport(bom=bom)
        workers = max(1, cfg.workers)

        # Phase 0: resolve the full recursive dependency closure. Each component's
        # actual dependency versions and target Java version (not the BOM's managed
        # versions, nor the javadoc's stale baked-in JDK prefix) are what crosslinking
        # targets. We resolve wave by wave, expanding the unpack set with every newly
        # discovered dependency, until the set reaches a fixpoint. This guarantees two
        # invariants: every unpacked component has a resolved closure (so none is
        # crosslinked against an empty index), AND every version any component
        # references is itself unpacked (so links resolve all the way down instead of
        # dangling at the dependency frontier). Refs to versions with no -javadoc JAR
        # still stay unlinked; the index simply skips absent dirs.
        closures: dict[str, Closure] = {}
        top_targets = components + extras
        unpack_targets: dict[str, Component] = {c.coordinate: c for c in top_targets}
        top_total = len(top_targets)

        def _resolve_wave(targets: list[Component], *, top_level: bool) -> None:
            with _pool(workers) as pool:
                futs = {pool.submit(resolve_closure, ctx, c): c for c in targets}
                for fut in as_completed(futs):
                    comp = futs[fut]
                    closure = fut.result()
                    closures[comp.coordinate] = closure
                    for dep in closure.deps:
                        unpack_targets.setdefault(dep.coordinate, dep)
                    if on_resolve is not None:
                        on_resolve(comp, top_level, top_total)

        pending = list(top_targets)
        top_level = True
        while pending:
            _resolve_wave(pending, top_level=top_level)
            top_level = False
            pending = [c for k, c in unpack_targets.items() if k not in closures]
        if on_plan is not None:
            on_plan(len(unpack_targets))

        empty_closure = Closure()

        # Phase 1: download + unpack + adjust every target (parallel, cached).
        with _pool(workers) as pool:
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

        # Phase 1b: generate javadoc from -sources JARs where no -javadoc JAR was
        # published. Runs after unpacking so that each generation can -linkoffline
        # against its dependencies' (exact-version) javadoc already in the tree.
        missing = [r for r in report.results if r.status == UnpackStatus.MISSING]
        if missing:
            with _pool(workers) as pool:
                gen_futures = {
                    pool.submit(
                        generate_component,
                        ctx,
                        r.component,
                        site,
                        closures.get(r.component.coordinate, empty_closure).deps,
                        closures.get(
                            r.component.coordinate, empty_closure
                        ).java_version,
                        url_prefix=cfg.url_prefix,
                    ): r
                    for r in missing
                }
                for gf in as_completed(gen_futures):
                    old_result = gen_futures[gf]
                    report.results[report.results.index(old_result)] = gf.result()

        # Phase 2: crosslink every unpacked component against its own closure.
        indexer = ClassIndexer(site)
        jdk_resolver = JdkModuleResolver(
            cfg.url_prefix, cfg.jdk_api_url_template, cfg.jdk_api_base_urls
        )
        with _pool(workers) as pool:
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
                    jdk_resolver=jdk_resolver,
                    force=cfg.force,
                )
                for comp in unpack_targets.values()
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
        # ...and its named unions over subsets of the BOM.
        for name, patterns in sorted(cfg.unions.items()):
            if not patterns:
                continue  # an empty include list would match everything
            members = ComponentFilter(includes=patterns).filter(components)
            report.named_unions[name] = build_union(
                site,
                bom,
                members,
                name=name,
                redirect_format=cfg.redirect_format,
            )
        _remove_stale_unions(report.union.union_dir, set(cfg.unions))

        # Phase 4: refresh the site-wide maps so they span every BOM version and
        # component on disk, not just this run's.
        report.site_maps = build_site_maps(site)
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
