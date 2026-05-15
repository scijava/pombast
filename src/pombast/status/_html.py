"""Generate an HTML status dashboard from a list of StatusEntry objects."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Iterable

from jinja2 import Environment, PackageLoader, select_autoescape

from pombast.status._drift import format_duration

if TYPE_CHECKING:
    from pombast.status._entry import StatusEntry


_COLUMNS = ["Artifact", "Release", "Drift", "Action", "Build"]

_env = Environment(
    loader=PackageLoader("pombast.status", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=False,
    lstrip_blocks=False,
)


def _css_safe(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "-", s)


def _nexus_link(g: str, a: str, v: str, nexus_base: str) -> str:
    if not nexus_base:
        return v
    return f'<a href="{nexus_base}/#nexus-search;gav~{g}~{a}~{v}~~">{v}</a>'


def _vetted_class(entry: StatusEntry) -> str:
    lv = entry.last_vetted
    vo = entry.vetting_override
    rt = entry.release_timestamp
    if lv is None:
        return ""
    if vo and rt and lv == vo and vo >= rt:
        return "overridden"
    if vo and rt and lv == rt and vo < rt:
        return "wasOverridden"
    return ""


def _drift_data(entry: StatusEntry) -> dict[str, Any]:
    """Build the data needed to render the Drift cell."""
    lv = entry.last_vetted
    lu = entry.last_updated
    base_cls = _vetted_class(entry)

    if lv is None and lu is None:
        return {"cls": "unknown", "sort_key": -1, "tooltip": "", "html": "???"}

    vetted_str = f"{lv:%Y-%m-%d %H:%M:%S}" if lv else "???"
    updated_str = f"{lu:%Y-%m-%d %H:%M:%S}" if lu else "???"
    tooltip = f"vetted: {vetted_str}\nupdated: {updated_str}"

    if lv is None or lu is None:
        cls = ("unknown " + base_cls).strip() if base_cls else "unknown"
        return {"cls": cls, "sort_key": -1, "tooltip": tooltip, "html": "???"}

    delta = int((lu - lv).total_seconds())
    if delta <= 0:
        return {
            "cls": base_cls,
            "sort_key": 0,
            "tooltip": tooltip,
            "html": '<span class="drift-none">&mdash;</span>',
        }
    return {
        "cls": base_cls,
        "sort_key": delta,
        "tooltip": tooltip,
        "html": format_duration(delta),
    }


def _row_data(entry: StatusEntry, nexus_base: str) -> dict[str, Any]:
    g = entry.component.group
    a = entry.component.name
    bom_v = entry.bom_version
    latest_v = entry.latest_version or bom_v
    action_key = {"Cut": 1, "Bump": 2, "None": 3}[entry.action]

    return {
        "group_css": _css_safe(g),
        "artifact_css": _css_safe(a),
        "bom_css": "bom-ok" if entry.bom_ok else "bom-behind",
        "release_css": "release-ok" if entry.release_ok else "release-needed",
        "artifact_label": f"{g} : {a}",
        "project_url": entry.project_url or "",
        "bom_version": bom_v,
        "latest_version": latest_v,
        "bom_link": _nexus_link(g, a, bom_v, nexus_base),
        "latest_link": _nexus_link(g, a, latest_v, nexus_base),
        "drift": _drift_data(entry),
        "action": entry.action,
        "action_key": action_key,
        "badge_html": entry.badge_html or "<td>-</td>",
    }


def generate_html(
    entries: Iterable[StatusEntry],
    *,
    nexus_base: str = "",
    title: str = "SciJava software status",
    footer_html: str = "",
) -> str:
    """Return a complete HTML page with the status dashboard table."""
    rows = [_row_data(entry, nexus_base) for entry in entries]
    template = _env.get_template("status.html.j2")
    return template.render(
        title=title,
        columns=_COLUMNS,
        rows=rows,
        footer_html=footer_html,
    )
