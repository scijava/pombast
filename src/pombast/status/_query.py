"""Fetch release status data for BOM components."""

from __future__ import annotations

import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING, Iterator

from pombast.cache._pom_timestamp import PomTimestampCache
from pombast.core._filter import ComponentFilter
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


def _make_badge_html(project_url: str, badge_overrides: dict[str, str]) -> str:
    """Return the HTML table cell for a GitHub Actions CI badge."""
    if not project_url or not project_url.startswith("https://github.com/"):
        return ""
    slug = project_url[len("https://github.com/") :]
    if slug in badge_overrides:
        return badge_overrides[slug]
    return (
        f'<td class="badge">'
        f'<a href="https://github.com/{slug}/actions">'
        f'<img data-src="https://github.com/{slug}/actions/workflows/build-main.yml/badge.svg">'
        f"</a></td>"
    )


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


def _fetch_one(
    comp: Component,
    ctx,
    rules: RulesXML,
    fetch_timestamps: bool,
    proj_ov: dict[str, str],
    badge_ov: dict[str, str],
    vetting_ov: dict[str, datetime],
    max_age: int | None,
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

    url = proj_ov.get(f"{g}:{a}") or _infer_project_url(g, a)
    badge = _make_badge_html(url, badge_ov)
    vetting = vetting_ov.get(f"{g}:{a}")

    return StatusEntry(
        component=comp,
        latest_version=latest,
        release_timestamp=release_ts,
        last_updated=last_updated,
        vetting_override=vetting,
        project_url=url,
        badge_html=badge,
    )


DEFAULT_MAX_AGE = 4 * 3600  # 4 hours


def query_status(
    bom_data: BomData,
    *,
    rules: RulesXML,
    project_overrides: dict[str, str] | None = None,
    badge_overrides: dict[str, str] | None = None,
    vetting_overrides: dict[str, datetime] | None = None,
    includes: list[str] | None = None,
    excludes: list[str] | None = None,
    fetch_timestamps: bool = True,
    workers: int = 8,
    max_age: int | None = DEFAULT_MAX_AGE,
) -> Iterator[StatusEntry]:
    """Yield a StatusEntry for each (filtered) component in the BOM.

    max_age controls how stale cached maven-metadata.xml files can be before
    they are re-fetched from the network.  Pass 0 or None to always refresh.
    POM Last-Modified timestamps are cached permanently (they never change
    once a version is released).
    """
    proj_ov = project_overrides or {}
    badge_ov = badge_overrides or {}
    vetting_ov = vetting_overrides or {}

    components = bom_data.components
    if includes or excludes:
        cf = ComponentFilter(includes=includes or [], excludes=excludes or [])
        components = cf.filter(components)

    ctx = bom_data.ctx

    args = (ctx, rules, fetch_timestamps, proj_ov, badge_ov, vetting_ov, max_age)

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
