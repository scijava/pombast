"""Aggregate per-developer workload from release status, POM roles, and GitHub stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pombast.status._entry import StatusEntry
    from pombast.team._github import RepoItem, RepoStats
    from pombast.team._pom_devs import Developer

# Roles that represent ongoing maintenance responsibility.
# "founder" is excluded — it's historical credit, not active duty.
MAINTENANCE_ROLES = {
    "lead",
    "developer",
    "debugger",
    "reviewer",
    "support",
    "maintainer",
}


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
    def total(self) -> int:
        return (
            self.reviewer_prs
            + self.support_issues
            + self.debugger_bugs
            + self.developer_features
            + self.maintainer_releases
        )


def build_workloads(
    entries: list[StatusEntry],
    dev_roles: dict[str, list[tuple[Developer, set[str]]]],
    repo_stats: dict[str, RepoStats],
) -> list[DeveloperRow]:
    """Build per-developer workload rows sorted by total workload descending.

    Args:
        entries: StatusEntry list from query_status (provides release status per component).
        dev_roles: G:A → [(Developer, roles)] from component POM <developers> sections.
        repo_stats: GitHub repo slug → RepoStats from the GitHub search API.
    """
    rows: dict[str, DeveloperRow] = {}

    for entry in entries:
        ga = entry.component.ga
        url = entry.project_url or ""
        slug = (
            url.removeprefix("https://github.com/")
            if url.startswith("https://github.com/")
            else None
        )
        stats = repo_stats.get(slug) if slug else None
        needs_release = entry.action == "Cut"

        for dev, roles in dev_roles.get(ga, []):
            if not (roles & MAINTENANCE_ROLES):
                continue

            if dev.id not in rows:
                rows[dev.id] = DeveloperRow(developer=dev)
            row = rows[dev.id]

            if ga not in row.components:
                row.components.append(ga)

            is_lead = "lead" in roles

            if stats:
                if is_lead or "reviewer" in roles:
                    for item in stats.prs:
                        row._prs.setdefault(item.url, item)
                if is_lead or "support" in roles:
                    for item in stats.issues:
                        row._issues.setdefault(item.url, item)
                if is_lead or "debugger" in roles:
                    for item in stats.bugs:
                        row._bugs.setdefault(item.url, item)
                if is_lead or "developer" in roles:
                    for item in stats.enhancements:
                        row._features.setdefault(item.url, item)

            if needs_release and (is_lead or "maintainer" in roles):
                row._releases.setdefault(ga, ReleaseItem(ga=ga, url=url))

    return sorted(rows.values(), key=lambda r: r.total, reverse=True)
