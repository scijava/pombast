"""Fetch release status data for BOM components."""

from __future__ import annotations

import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING, Iterator

from pombast.cache._pom_timestamp import PomTimestampCache
from pombast.core._filter import ComponentFilter
from pombast.maven._bytecode import BumpClassifier, candidate_floor
from pombast.status._entry import StatusEntry

if TYPE_CHECKING:
    from pombast.core._component import Component
    from pombast.maven._bom import BomData
    from pombast.maven._rules import RulesXML

_pom_ts_cache = PomTimestampCache()

_log = logging.getLogger(__name__)

# Maps groupId prefix to the GitHub organization that hosts its projects.
_GROUP_ORGS: dict[str, str] = {
    "graphics.scenery": "scenerygraphics",
    "io.scif": "scifio",
    "net.imagej": "imagej",
    "net.imglib2": "imglib",
    "org.openmicroscopy": "ome",
    "org.scijava": "scijava",
    "sc.fiji": "fiji",
    "sc.iview": "scenerygraphics",
}


def _parse_ts(value: str) -> datetime:
    """Parse a YYYYMMDDHHmmss timestamp string into a datetime."""
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", value.strip())
    if not m:
        raise ValueError(f"Cannot parse timestamp: {value!r}")
    return datetime(*map(int, m.groups()))  # type: ignore[arg-type]


def load_kv_file(path: str) -> dict[str, str]:
    """Load a whitespace-delimited key→value file, skipping blank lines and comments."""
    result: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                result[parts[0]] = parts[1]
    return result


def load_timestamps_file(path: str) -> dict[str, datetime]:
    """Load a vetting timestamps file mapping G:A → datetime."""
    result: dict[str, datetime] = {}
    for ga, ts_str in load_kv_file(path).items():
        try:
            result[ga] = _parse_ts(ts_str)
        except ValueError:
            _log.warning("Skipping invalid timestamp for %s: %r", ga, ts_str)
    return result


def _infer_project_url(group_id: str, artifact_id: str) -> str:
    """Derive a GitHub URL from a component's groupId/artifactId."""
    g, a = group_id, artifact_id
    if g == "sc.fiji":
        if a.startswith("TrackMate"):
            return f"https://github.com/trackmate-sc/{a}"
        if a.startswith("bigdataviewer"):
            return f"https://github.com/bigdataviewer/{a}"
        if a.startswith("labkit"):
            return f"https://github.com/juglab/{a}"
        if a.endswith("_"):
            a = a[:-1]
    if g in _GROUP_ORGS:
        return f"https://github.com/{_GROUP_ORGS[g]}/{a}"
    return ""


def _ensure_yaml_ext(name: str) -> str:
    return name if (name.endswith(".yml") or name.endswith(".yaml")) else name + ".yml"


def _make_ci_html(
    project_url: str,
    workflow: str | bool | None,
    default_workflow: str = "build",
) -> str:
    """Return the HTML table cell for a GitHub Actions CI badge."""
    if not project_url or not project_url.startswith("https://github.com/"):
        return ""
    if workflow is False:
        return ""
    slug = project_url[len("https://github.com/") :]
    wf = _ensure_yaml_ext(workflow if isinstance(workflow, str) else default_workflow)
    return f'<td class="ci" data-slug="{slug}" data-wf="{wf}"></td>'


def _scm_project_url(ctx, group_id: str, artifact_id: str, version: str) -> str:
    """Extract a GitHub project URL from a release POM's scm/url field."""
    try:
        pom = ctx.project(group_id, artifact_id).at_version(version).pom()
        url = pom.value("scm/url")
        if url and url.startswith("https://github.com/"):
            return url.removesuffix(".git")
    except Exception:
        pass
    return ""


def _pom_last_modified(
    ctx,
    group_id: str,
    artifact_id: str,
    version: str,
) -> datetime | None:
    """Return Last-Modified timestamp of a release POM, using a persistent cache."""
    cached = _pom_ts_cache.get(group_id, artifact_id, version)
    if cached is not None:
        return cached

    ts = (
        ctx.project(group_id, artifact_id)
        .at_version(version)
        .artifact(packaging="pom")
        .last_modified()
    )
    if ts is not None:
        _pom_ts_cache.put(group_id, artifact_id, version, ts)
    return ts


def _scan_candidate_floor(
    ctx,
    group_id: str,
    artifact_id: str,
    version: str,
    current_own: int | None,
    current_effective: int | None,
) -> int | None:
    """Estimate a candidate version's effective bytecode floor.

    Scans the candidate's published JAR for its own bytecode (jgo caches the
    scan per artifact) and combines it with the current closure's contribution.
    Best-effort: returns None if the JAR cannot be resolved or scanned.
    """
    from jgo.env import jar_java_version

    own_new: int | None = None
    try:
        artifact = ctx.project(group_id, artifact_id).at_version(version).artifact()
        own_new = jar_java_version(artifact, round_to_lts_version=False)
    except Exception:
        own_new = None
    return candidate_floor(own_new, current_own, current_effective)


def _classify_bumps(
    comp: Component,
    ctx,
    rules: RulesXML,
    versions: list[str],
    classifier: BumpClassifier,
    smelt_entry: dict,
    scan_cap: int,
) -> tuple[str | None, str | None, list]:
    """Classify a component's accepted bumps; return (recommended, frontier, ladder)."""
    g, a = comp.group, comp.name
    candidates = rules.acceptable_above(g, a, versions, comp.version)[:scan_cap]
    if not candidates:
        return None, None, []
    current_own = smelt_entry.get("own_bytecode")
    current_effective = smelt_entry.get("effective_bytecode")
    scanned = [
        (
            v,
            _scan_candidate_floor(ctx, g, a, v, current_own, current_effective),
        )
        for v in candidates
    ]
    result = classifier.classify(comp.ga, scanned)
    return result.recommended, result.frontier_class, result.ladder


def _fetch_one(
    comp: Component,
    ctx,
    rules: RulesXML,
    fetch_timestamps: bool,
    proj_ov: dict[str, str],
    comp_ov: dict[str, dict],
    vetting_ov: dict[str, datetime],
    max_age: int | None,
    default_workflow: str,
    badges_filter: ComponentFilter | None,
    cuttable_filter: ComponentFilter | None,
    classifier: BumpClassifier | None,
    smelt_components: dict[str, dict] | None,
    scan_cap: int,
) -> StatusEntry:
    g, a = comp.group, comp.name
    _log.info("Querying %s:%s", g, a)

    project = ctx.project(g, a)
    project.update(max_age=max_age)

    latest = rules.latest_acceptable(g, a, project.metadata.versions)

    release_ts: datetime | None = None
    last_updated: datetime | None = None

    if fetch_timestamps and latest:
        release_ts = _pom_last_modified(ctx, g, a, latest)
        last_updated = project.metadata.lastUpdated

    comp_data = comp_ov.get(f"{g}:{a}", {})
    url = (
        comp_data.get("project-url")
        or proj_ov.get(f"{g}:{a}")
        or _scm_project_url(ctx, g, a, comp.version)
        or _infer_project_url(g, a)
    )
    ci_build = comp_data.get("ci-build")
    workflow: str | bool | None = (
        ci_build if isinstance(ci_build, (str, bool)) else None
    )
    badges_ok = badges_filter is None or badges_filter.is_included(comp)
    ci = _make_ci_html(url, workflow, default_workflow) if badges_ok else ""
    raw_vetted = comp_data.get("last-vetted")
    vetting = (
        _parse_ts(str(raw_vetted))
        if raw_vetted is not None
        else vetting_ov.get(f"{g}:{a}")
    )
    cuttable = cuttable_filter is None or cuttable_filter.is_included(comp)

    recommended: str | None = None
    frontier: str | None = None
    ladder: list = []
    if classifier is not None and smelt_components is not None:
        smelt_entry = smelt_components.get(f"{g}:{a}")
        # Only worth scanning candidate JARs when we know this component's current
        # floor; without it every candidate classifies "unknown" anyway.
        if (
            smelt_entry is not None
            and smelt_entry.get("effective_bytecode") is not None
        ):
            recommended, frontier, ladder = _classify_bumps(
                comp,
                ctx,
                rules,
                project.metadata.versions,
                classifier,
                smelt_entry,
                scan_cap,
            )

    return StatusEntry(
        component=comp,
        latest_version=latest,
        release_timestamp=release_ts,
        last_updated=last_updated,
        vetting_override=vetting,
        project_url=url,
        ci_html=ci,
        cuttable=cuttable,
        recommended_version=recommended,
        frontier_class=frontier,
        version_ladder=ladder,
    )


DEFAULT_MAX_AGE = 4 * 3600  # 4 hours


def query_status(
    bom_data: BomData,
    *,
    rules: RulesXML,
    project_overrides: dict[str, str] | None = None,
    component_overrides: dict[str, dict] | None = None,
    vetting_overrides: dict[str, datetime] | None = None,
    includes: list[str] | None = None,
    excludes: list[str] | None = None,
    badges_includes: list[str] | None = None,
    badges_excludes: list[str] | None = None,
    cuttable: list[str] | None = None,
    fetch_timestamps: bool = True,
    workers: int = 8,
    max_age: int | None = DEFAULT_MAX_AGE,
    default_workflow: str = "build",
    smelt_components: dict[str, dict] | None = None,
    classify: bool = False,
    runtime_cap: int = 21,
    scan_cap: int = 16,
) -> Iterator[StatusEntry]:
    """Yield a StatusEntry for each (filtered) component in the BOM.

    max_age controls how stale cached maven-metadata.xml files can be before
    they are re-fetched from the network.  Pass 0 or None to always refresh.
    POM Last-Modified timestamps are cached permanently (they never change
    once a version is released).

    When ``classify`` is set and ``smelt_components`` (bytecode floors + closures
    from a prior smelt run) is provided, each accepted bump is classified by its
    bytecode-floor blast radius. This scans candidate JARs, so it is opt-in.
    """
    proj_ov = project_overrides or {}
    comp_ov = component_overrides or {}
    vetting_ov = vetting_overrides or {}

    classifier: BumpClassifier | None = None
    if classify and smelt_components:
        floors = {
            ga: data["effective_bytecode"]
            for ga, data in smelt_components.items()
            if data.get("effective_bytecode") is not None
        }
        closures = {
            ga: data["closure"]
            for ga, data in smelt_components.items()
            if data.get("closure")
        }
        classifier = BumpClassifier(
            floors=floors, closures=closures, runtime_cap=runtime_cap
        )

    components = bom_data.components
    if includes or excludes:
        cf = ComponentFilter(includes=includes or [], excludes=excludes or [])
        components = cf.filter(components)

    badges_filter: ComponentFilter | None = None
    if badges_includes or badges_excludes:
        badges_filter = ComponentFilter(
            includes=badges_includes or [], excludes=badges_excludes or []
        )

    cuttable_filter: ComponentFilter | None = None
    if cuttable:
        cuttable_filter = ComponentFilter(includes=cuttable)

    ctx = bom_data.ctx

    args = (
        ctx,
        rules,
        fetch_timestamps,
        proj_ov,
        comp_ov,
        vetting_ov,
        max_age,
        default_workflow,
        badges_filter,
        cuttable_filter,
        classifier,
        smelt_components,
        scan_cap,
    )

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures: list[Future[StatusEntry]] = [
                pool.submit(_fetch_one, comp, *args) for comp in components
            ]
            for future in futures:
                yield future.result()
    else:
        for comp in components:
            yield _fetch_one(comp, *args)
