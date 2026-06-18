"""Generate team accountability report (static HTML shell + team.json data).

The HTML page is a near-static shell: it ships an empty table and fetches
``team.json`` at runtime to build the rows and popups client-side. Keeping all
volatile data in ``team.json`` (sorted by developer id, indented) means the
committed ``team.html`` only changes when the template itself changes, and the
``team.json`` diffs are stable and line-by-line readable. This mirrors the
``badges.json`` / ``smelt.json`` convention used elsewhere.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Iterable

from jinja2 import Environment, PackageLoader, select_autoescape

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.team._workload import DeveloperRow

_env = Environment(
    loader=PackageLoader("pombast.team", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _item_dict(item) -> dict:
    return {
        "url": item.url,
        "title": item.title,
        "number": item.number,
        "repo": item.repo,
    }


def _row_data(r: DeveloperRow) -> dict:
    dev = r.developer
    return {
        "dev_id": dev.id,
        "dev_name": dev.name or dev.id,
        "dev_url": dev.url or f"https://github.com/{dev.id}",
        "reviewer_prs": r.reviewer_prs,
        "support_issues": r.support_issues,
        "debugger_bugs": r.debugger_bugs,
        "developer_features": r.developer_features,
        "maintainer_releases": r.maintainer_releases,
        "total": r.total,
        "component_count": len(r.components),
        "popups": {
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
        },
    }


def build_team_data(
    rows: Iterable[DeveloperRow],
    *,
    generated: str = "",
) -> dict:
    """Build the JSON-serializable team.json payload.

    Rows are sorted by developer id so the file diffs are stable over time; the
    default view (by total workload) is applied client-side.
    """
    row_list = sorted((_row_data(r) for r in rows), key=lambda d: d["dev_id"])
    return {"generated": generated, "rows": row_list}


def write_team_json(path: Path, data: dict) -> None:
    """Write team.json with stable, line-by-line-diffable formatting."""
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def generate_team_html(
    *,
    title: str = "SciJava team status",
    header_html: str = "",
    footer_html: str = "",
    data_url: str = "team.json",
) -> str:
    """Return the static HTML shell that renders ``team.json`` client-side."""
    template = _env.get_template("team.html.j2")
    return template.render(
        title=title,
        header_html=header_html,
        footer_html=footer_html,
        data_url=data_url,
    )
