"""Generate team accountability HTML report."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from jinja2 import Environment, PackageLoader, select_autoescape

if TYPE_CHECKING:
    from pombast.team._workload import DeveloperRow

_env = Environment(
    loader=PackageLoader("pombast.team", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _dev_link(row: DeveloperRow) -> str:
    dev = row.developer
    label = dev.name or dev.id
    url = dev.url or f"https://github.com/{dev.id}"
    return f'<a href="{url}">{label}</a>'


def generate_team_html(
    rows: Iterable[DeveloperRow],
    *,
    title: str = "SciJava team status",
    generated: str = "",
) -> str:
    """Return a complete HTML page with the team accountability table."""

    def _row_data(r: DeveloperRow) -> dict:
        return {
            "dev_link": _dev_link(r),
            "dev_id": r.developer.id,
            "reviewer_prs": r.reviewer_prs,
            "support_issues": r.support_issues,
            "debugger_bugs": r.debugger_bugs,
            "developer_features": r.developer_features,
            "maintainer_releases": r.maintainer_releases,
            "total": r.total,
            "component_count": len(r.components),
            "components": sorted(r.components),
        }

    template = _env.get_template("team.html.j2")
    return template.render(
        title=title,
        generated=generated,
        rows=[_row_data(r) for r in rows],
    )
