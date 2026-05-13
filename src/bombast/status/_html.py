"""Generate an HTML status dashboard from a list of StatusEntry objects."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from bombast.status._entry import StatusEntry

_CHECK = "&#x2714;"
_CROSS = "&#x2715;"


def _css_safe(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "-", s)


def _nexus_link(g: str, a: str, v: str, nexus_base: str) -> str:
    if not nexus_base:
        return v
    return f'<a href="{nexus_base}/#nexus-search;gav~{g}~{a}~{v}~~">{v}</a>'


def _vetted_cell(entry: StatusEntry) -> str:
    lv = entry.last_vetted
    if lv is None:
        return '<td class="unknown">???</td>'
    ts = f"{lv:%Y-%m-%d %H:%M:%S}"
    vo = entry.vetting_override
    rt = entry.release_timestamp
    if vo and rt and lv == vo and vo >= rt:
        # Vetting override is the most recent check.
        return f'<td class="overridden">{ts}</td>'
    if vo and rt and lv == rt and vo < rt:
        # Release is newer, but an older manual override still exists.
        return f'<td class="wasOverridden">{ts}</td>'
    return f"<td>{ts}</td>"


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

        bom_ok_mark = _CHECK if entry.bom_ok else _CROSS
        rel_ok_mark = _CHECK if entry.release_ok else _CROSS
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

        lu = entry.last_updated
        updated_cell = (
            f"<td>{lu:%Y-%m-%d %H:%M:%S}</td>" if lu else '<td class="unknown">???</td>'
        )

        badge_cell = entry.badge_html or "<td>-</td>"

        gc = _css_safe(g)
        ac = _css_safe(a)
        rows.append(
            f'<tr class="g-{gc} a-{ac} {bom_css} {rel_css}">'
            f"{artifact_cell}"
            f"{release_cell}"
            f"<td>{bom_ok_mark}</td>"
            f"{_vetted_cell(entry)}"
            f"{updated_cell}"
            f"<td>{rel_ok_mark}</td>"
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
<th>OK</th>
<th>Last vetted</th>
<th>Last updated</th>
<th>OK</th>
<th>Action</th>
<th>Build</th>
</tr>
{rows_html}
</table>
{footer_html}
</body>
</html>
"""
