"""Generate team accountability HTML report."""

from __future__ import annotations

import json
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


def _item_dict(item) -> dict:
    return {
        "url": item.url,
        "title": item.title,
        "number": item.number,
        "repo": item.repo,
    }


def generate_team_html(
    rows: Iterable[DeveloperRow],
    *,
    title: str = "SciJava team status",
    generated: str = "",
) -> str:
    """Return a complete HTML page with the team accountability table."""

    popup_data: dict[str, dict] = {}

    def _row_data(r: DeveloperRow) -> dict:
        dev_id = r.developer.id
        popup_data[dev_id] = {
            "reviewer_prs": [_item_dict(i) for i in r.reviewer_pr_items],
            "support_issues": [_item_dict(i) for i in r.support_issue_items],
            "debugger_bugs": [_item_dict(i) for i in r.debugger_bug_items],
            "developer_features": [_item_dict(i) for i in r.developer_feature_items],
            "maintainer_releases": [
                {"ga": i.ga, "url": i.url} for i in r.maintainer_release_items
            ],
            "components": [
                {"ga": ga, "url": url} for ga, url in r.component_url_items
            ],
        }
        return {
            "dev_link": _dev_link(r),
            "dev_id": dev_id,
            "reviewer_prs": r.reviewer_prs,
            "support_issues": r.support_issues,
            "debugger_bugs": r.debugger_bugs,
            "developer_features": r.developer_features,
            "maintainer_releases": r.maintainer_releases,
            "total": r.total,
            "component_count": len(r.components),
        }

    row_list = [_row_data(r) for r in rows]
    template = _env.get_template("team.html.j2")
    return template.render(
        title=title,
        generated=generated,
        rows=row_list,
        popup_data_json=json.dumps(popup_data) if popup_data else None,
    )
