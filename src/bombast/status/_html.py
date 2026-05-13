"""Generate an HTML status dashboard from a list of StatusEntry objects."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from bombast.status._entry import StatusEntry


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


def _format_duration(seconds: int) -> str:
    """Render a non-negative duration in seconds as a compact human string."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    days = hours // 24
    if days < 14:
        return f"{days}d"
    if days < 60:
        return f"{days // 7}w"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def _drift_cell(entry: StatusEntry) -> str:
    lv = entry.last_vetted
    lu = entry.last_updated
    if lv is None and lu is None:
        return '<td class="unknown" sorttable_customkey="-1">???</td>'
    vetted_str = f"{lv:%Y-%m-%d %H:%M:%S}" if lv else "???"
    updated_str = f"{lu:%Y-%m-%d %H:%M:%S}" if lu else "???"
    tooltip = f"vetted: {vetted_str}&#10;updated: {updated_str}"
    cls = _vetted_class(entry)
    if lv is None or lu is None:
        cls_attr = f' class="unknown {cls}"'.strip() if cls else ' class="unknown"'
        return f'<td{cls_attr} sorttable_customkey="-1" title="{tooltip}">???</td>'
    delta = int((lu - lv).total_seconds())
    if delta <= 0:
        cls_attr = f' class="{cls}"' if cls else ""
        return (
            f'<td{cls_attr} sorttable_customkey="0" title="{tooltip}">'
            f'<span class="drift-none">&mdash;</span></td>'
        )
    cls_attr = f' class="{cls}"' if cls else ""
    return (
        f'<td{cls_attr} sorttable_customkey="{delta}" title="{tooltip}">'
        f"{_format_duration(delta)}</td>"
    )


def generate_html(
    entries: Iterable[StatusEntry],
    *,
    nexus_base: str = "",
    title: str = "SciJava software status",
    footer_html: str = "",
) -> str:
    """Return a complete HTML page with the status dashboard table."""
    rows: list[str] = []

    for entry in entries:
        g = entry.component.group
        a = entry.component.name
        bom_v = entry.bom_version
        latest_v = entry.latest_version or bom_v
        url = entry.project_url or ""

        bom_css = "bom-ok" if entry.bom_ok else "bom-behind"
        rel_css = "release-ok" if entry.release_ok else "release-needed"
        action_key = {"Cut": 1, "Bump": 2, "None": 3}[entry.action]

        artifact_cell = (
            f'<td><a href="{url}">{g} : {a}</a></td>' if url else f"<td>{g} : {a}</td>"
        )

        if bom_v == latest_v:
            release_cell = f"<td>{_nexus_link(g, a, latest_v, nexus_base)}</td>"
        else:
            release_cell = (
                f"<td>{_nexus_link(g, a, bom_v, nexus_base)} &rarr; "
                f"{_nexus_link(g, a, latest_v, nexus_base)}</td>"
            )

        badge_cell = entry.badge_html or "<td>-</td>"

        gc = _css_safe(g)
        ac = _css_safe(a)
        rows.append(
            f'<tr class="g-{gc} a-{ac} {bom_css} {rel_css}">'
            f"{artifact_cell}"
            f"{release_cell}"
            f"{_drift_cell(entry)}"
            f'<td sorttable_customkey="{action_key}">{entry.action}</td>'
            f"{badge_cell}"
            f"</tr>"
        )

    rows_html = "\n".join(rows)
    return f"""\
<!DOCTYPE html>
<html>
<head>
<title>{title}</title>
<link type="text/css" rel="stylesheet" href="status.css">
<link rel="icon" type="image/png" href="favicon.png">
<script type="text/javascript" src="sorttable.js"></script>
</head>
<body>
<script type="text/javascript" src="sortable-badges.js"></script>
<!-- Generated via https://codepo8.github.io/css-fork-on-github-ribbon/ -->
<span id="forkongithub"><a href="https://github.com/scijava/status.scijava.org">Fix me on GitHub</a></span>
<table class="sortable">
<tr>
<th>Artifact</th>
<th>Release</th>
<th>Drift</th>
<th>Action</th>
<th>Build</th>
</tr>
{rows_html}
</table>
{footer_html}
</body>
</html>
"""
