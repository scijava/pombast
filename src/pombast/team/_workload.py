"""Aggregate per-developer workload from release status, POM roles, and GitHub stats."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pombast.status._entry import StatusEntry
    from pombast.team._github import RepoStats
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
class DeveloperRow:
    developer: Developer
    reviewer_prs: int = 0  # open PRs to review (reviewer or lead)
    support_issues: int = 0  # open issues to answer (support or lead)
    debugger_bugs: int = 0  # open bug reports (debugger or lead)
    developer_features: int = 0  # open enhancement requests (developer or lead)
    maintainer_releases: int = (
        0  # components with unreleased changes (maintainer or lead)
    )
    components: list[str] = field(default_factory=list)

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
                    row.reviewer_prs += stats.prs
                if is_lead or "support" in roles:
                    row.support_issues += stats.issues
                if is_lead or "debugger" in roles:
                    row.debugger_bugs += stats.bugs
                if is_lead or "developer" in roles:
                    row.developer_features += stats.enhancements

            if needs_release and (is_lead or "maintainer" in roles):
                row.maintainer_releases += 1

    return sorted(rows.values(), key=lambda r: r.total, reverse=True)
