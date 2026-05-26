"""Aggregate per-developer workload from release status, POM roles, and GitHub stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pombast.config._settings import PombastConfig
    from pombast.status._entry import StatusEntry
    from pombast.team._github import RepoItem, RepoStats
    from pombast.team._pom_devs import Developer


@dataclass
class ReleaseItem:
    ga: str  # e.g. "net.imagej:imagej-common"
    url: str  # project URL (GitHub repo page)


@dataclass
class DeveloperRow:
    developer: Developer
    # Dicts keyed by URL for deduplication across components sharing a repo.
    _prs: dict[str, RepoItem] = field(default_factory=dict)
    _issues: dict[str, RepoItem] = field(default_factory=dict)
    _bugs: dict[str, RepoItem] = field(default_factory=dict)
    _features: dict[str, RepoItem] = field(default_factory=dict)
    _releases: dict[str, ReleaseItem] = field(default_factory=dict)  # ga → item
    components: list[str] = field(default_factory=list)
    _component_urls: dict[str, str] = field(default_factory=dict)  # ga → project URL

    @property
    def reviewer_prs(self) -> int:
        return len(self._prs)

    @property
    def reviewer_pr_items(self) -> list[RepoItem]:
        return list(self._prs.values())

    @property
    def support_issues(self) -> int:
        return len(self._issues)

    @property
    def support_issue_items(self) -> list[RepoItem]:
        return list(self._issues.values())

    @property
    def debugger_bugs(self) -> int:
        return len(self._bugs)

    @property
    def debugger_bug_items(self) -> list[RepoItem]:
        return list(self._bugs.values())

    @property
    def developer_features(self) -> int:
        return len(self._features)

    @property
    def developer_feature_items(self) -> list[RepoItem]:
        return list(self._features.values())

    @property
    def maintainer_releases(self) -> int:
        return len(self._releases)

    @property
    def maintainer_release_items(self) -> list[ReleaseItem]:
        return list(self._releases.values())

    @property
    def component_url_items(self) -> list[tuple[str, str]]:
        return [(ga, self._component_urls.get(ga, "")) for ga in sorted(self.components)]

    @property
    def total(self) -> int:
        return (
            self.reviewer_prs
            + self.support_issues
            + self.debugger_bugs
            + self.developer_features
            + self.maintainer_releases
        )


def _effective_role_mapping(
    ga: str,
    pombast_config: PombastConfig,
) -> dict[str, set[str]]:
    """Return {semantic_key: {pom_role_strings}} for this component.

    Starts from global [team] role mappings and applies per-component overrides
    from [components."g:a"] sections.
    """
    base: dict[str, set[str]] = {
        key: set(vals) for key, vals in pombast_config.team.role_mapping().items()
    }
    ov = pombast_config.component_overrides.get(ga, {})
    for key in base:
        if key in ov:
            val = ov[key]
            base[key] = {val} if isinstance(val, str) else set(str(v) for v in val)
    return base


def _semantic_roles(
    pom_roles: set[str],
    mapping: dict[str, set[str]],
) -> set[str]:
    """Map POM role strings to semantic role keys using the given mapping."""
    return {key for key, pom_names in mapping.items() if pom_roles & pom_names}


def build_workloads(
    entries: list[StatusEntry],
    dev_roles: dict[str, list[tuple[Developer, set[str]]]],
    repo_stats: dict[str, RepoStats],
    pombast_config: PombastConfig | None = None,
) -> list[DeveloperRow]:
    """Build per-developer workload rows sorted by total workload descending.

    Args:
        entries: StatusEntry list from query_status (provides release status per component).
        dev_roles: G:A → [(Developer, roles)] from component POM <developers> sections.
        repo_stats: GitHub repo slug → RepoStats from the GitHub search API.
        pombast_config: Full pombast config (for role mappings, team includes/excludes).
    """
    from pombast.config._settings import PombastConfig
    from pombast.core._filter import ComponentFilter

    if pombast_config is None:
        pombast_config = PombastConfig.empty()

    team_cfg = pombast_config.team
    team_filter = ComponentFilter(includes=team_cfg.includes, excludes=team_cfg.excludes)

    rows: dict[str, DeveloperRow] = {}

    for entry in entries:
        if not team_filter.is_included(entry.component):
            continue

        ga = entry.component.ga
        url = entry.project_url or ""
        slug = (
            url.removeprefix("https://github.com/")
            if url.startswith("https://github.com/")
            else None
        )
        stats = repo_stats.get(slug) if slug else None
        needs_release = entry.action == "Cut"

        role_mapping = _effective_role_mapping(ga, pombast_config)

        for dev, pom_roles in dev_roles.get(ga, []):
            semantic = _semantic_roles(pom_roles, role_mapping)
            if not semantic:
                continue

            if dev.id not in rows:
                rows[dev.id] = DeveloperRow(developer=dev)
            row = rows[dev.id]

            if ga not in row.components:
                row.components.append(ga)
            row._component_urls.setdefault(ga, url)

            if stats:
                if "reviewer" in semantic:
                    for item in stats.prs:
                        row._prs.setdefault(item.url, item)
                if "support" in semantic:
                    for item in stats.issues:
                        row._issues.setdefault(item.url, item)
                if "debugger" in semantic:
                    for item in stats.bugs:
                        row._bugs.setdefault(item.url, item)
                if "developer" in semantic:
                    for item in stats.enhancements:
                        row._features.setdefault(item.url, item)

            if needs_release and "maintainer" in semantic:
                row._releases.setdefault(ga, ReleaseItem(ga=ga, url=url))

    return sorted(rows.values(), key=lambda r: r.total, reverse=True)
