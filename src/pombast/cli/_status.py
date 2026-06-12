"""pombast status subcommand."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import rich_click as click
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from pombast.config._settings import PombastConfig, parse_repo_spec
from pombast.core._filter import ComponentFilter
from pombast.core._smelt_json import load_smelt_components
from pombast.maven._bom import load_bom
from pombast.maven._rules import RulesXML
from pombast.status._drift import drift_text
from pombast.status._html import generate_html
from pombast.status._query import (
    DEFAULT_MAX_AGE,
    load_kv_file,
    load_timestamps_file,
    query_status,
)

if TYPE_CHECKING:
    from pombast.status._entry import StatusEntry

console = Console()


@click.command("status")
@click.argument("bom")
@click.option(
    "-i",
    "--include",
    multiple=True,
    help="G:A pattern to include (repeatable, wildcards OK).",
)
@click.option(
    "-e",
    "--exclude",
    multiple=True,
    help="G:A pattern to exclude (repeatable, wildcards OK).",
)
@click.option(
    "-r",
    "--repository",
    multiple=True,
    help="Additional remote Maven repository URL (repeatable). Optionally prefix with a name: name=URL.",
)
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to pombast.toml configuration file.",
)
@click.option(
    "--rules",
    default=None,
    help="Path or URL to versions-maven-plugin rules.xml (omit to accept all versions).",
)
@click.option(
    "--projects",
    default=None,
    help="Path to project URL overrides file (G:A <space> URL per line).",
)
@click.option(
    "--timestamps",
    default=None,
    help="Path to vetting timestamps file (G:A <space> YYYYMMDDHHmmss per line).",
)
@click.option(
    "--smelt",
    "smelt_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to smelt.json to overlay binary/source compatibility columns.",
)
@click.option(
    "--no-timestamps",
    is_flag=True,
    help="Skip HTTP timestamp fetching for faster (release-only) output.",
)
@click.option(
    "--workers",
    default=8,
    show_default=True,
    type=int,
    help="Number of parallel HTTP workers.",
)
@click.option(
    "--max-age",
    default=DEFAULT_MAX_AGE,
    show_default=True,
    type=int,
    help="Re-fetch maven-metadata.xml only if cached copy is older than this many seconds.",
)
@click.option(
    "--refresh",
    is_flag=True,
    help="Ignore all caches and fetch fresh data (equivalent to --max-age 0).",
)
@click.option(
    "--nexus-base",
    "nexus_base",
    default=None,
    help="Nexus base URL for artifact hyperlinks in the HTML report (e.g. https://maven.scijava.org).",
)
@click.option(
    "--html",
    "html_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write HTML status report to this file.",
)
@click.option(
    "--header",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="HTML fragment to inject inside <body> before the main table.",
)
@click.option(
    "--footer",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="HTML fragment to append inside <body> after the main table.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
def status_cmd(
    bom: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    repository: tuple[str, ...],
    config: Path | None,
    rules: str | None,
    projects: str | None,
    timestamps: str | None,
    smelt_path: Path | None,
    no_timestamps: bool,
    nexus_base: str | None,
    html_path: Path | None,
    header: Path | None,
    footer: Path | None,
    workers: int,
    max_age: int,
    refresh: bool,
    verbose: bool,
) -> None:
    """Show release status of all components in a BOM.

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pombast_config = PombastConfig.load_default(config)
    sc = pombast_config.status
    effective_rules = rules or (str(sc.rules) if sc.rules else None)
    effective_projects = projects or (str(sc.projects) if sc.projects else None)
    effective_timestamps = timestamps or (str(sc.timestamps) if sc.timestamps else None)
    effective_html = html_path or sc.html
    effective_header = header or sc.header
    effective_footer = footer or sc.footer
    effective_nexus_base = nexus_base or sc.nexus_base
    effective_max_age = 0 if refresh else max_age

    console.print(f"[bold]BOM:[/bold] [cyan]{bom}[/cyan]")
    # Config repos come first, then CLI repos; load_bom appends central as last resort.
    repos = {
        **pombast_config.repositories,
        **{
            k: v
            for i, spec in enumerate(repository)
            for k, v in [parse_repo_spec(spec, f"repo{i}")]
        },
    }

    bom_data = load_bom(bom, repositories=repos)
    console.print(f"Loaded [bold]{len(bom_data.components)}[/bold] components.")
    if effective_max_age:
        console.print(
            f"Metadata cache TTL: [bold]{effective_max_age // 3600}h "
            f"{(effective_max_age % 3600) // 60}m[/bold]  "
            f"(use [bold]--refresh[/bold] to bypass)"
        )

    if effective_rules:
        console.print(f"Loading rules: [cyan]{effective_rules}[/cyan]")
        rules_xml = RulesXML.load(effective_rules)
    else:
        rules_xml = RulesXML.empty()

    proj_ov = load_kv_file(effective_projects) if effective_projects else {}
    vetting_ov = (
        load_timestamps_file(effective_timestamps) if effective_timestamps else {}
    )

    smelt_components: dict[str, dict] | None = None
    if smelt_path:
        smelt_components = load_smelt_components(smelt_path)
        console.print(
            f"Loaded smelt data: [bold]{len(smelt_components)}[/bold] components "
            f"([cyan]{smelt_path}[/cyan])"
        )

    cf = ComponentFilter(includes=list(include), excludes=list(exclude))
    total = len(cf.filter(bom_data.components))
    bc = pombast_config.badges

    entries: list[StatusEntry] = []
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Querying…", total=total)
        for entry in query_status(
            bom_data,
            rules=rules_xml,
            project_overrides=proj_ov,
            component_overrides=pombast_config.component_overrides,
            vetting_overrides=vetting_ov,
            default_workflow=sc.default_ci_badge,
            includes=list(include),
            excludes=list(exclude),
            badges_includes=bc.includes or None,
            badges_excludes=bc.excludes or None,
            cuttable=sc.cuttable or None,
            fetch_timestamps=not no_timestamps,
            workers=workers,
            max_age=effective_max_age or None,
        ):
            entries.append(entry)
            progress.update(
                task,
                advance=1,
                description=f"{entry.component.group}:{entry.component.name}",
            )

    _print_status_table(entries, smelt=smelt_components)

    cuts = sum(1 for e in entries if e.action == "Cut")
    bumps = sum(1 for e in entries if e.action == "Bump")
    console.print(
        f"\n[bold]Summary:[/bold] "
        f"[red]Cut {cuts}[/red]  "
        f"[yellow]Bump {bumps}[/yellow]  "
        f"[dim]None {len(entries) - cuts - bumps}[/dim]"
    )

    if effective_html:
        header_html = effective_header.read_text() if effective_header else ""
        footer_html = effective_footer.read_text() if effective_footer else ""
        effective_html.write_text(
            generate_html(
                entries,
                nexus_base=effective_nexus_base,
                header_html=header_html,
                footer_html=footer_html,
            )
        )
        console.print(f"HTML report written to: [cyan]{effective_html}[/cyan]")


def _smelt_cells(comp_data: dict | None, bom_version: str) -> tuple[str, str]:
    """Return (binary_cell, source_cell) Rich markup for a smelt component entry."""
    if comp_data is None:
        return "[dim]—[/dim]", "[dim]—[/dim]"

    mismatch = comp_data.get("version") not in (None, bom_version)
    suffix = "[yellow]*[/yellow]" if mismatch else ""
    skipped = comp_data.get("skipped_reason")

    def _render(status: str | None) -> str:
        if status == "pass":
            return f"[green]pass[/green]{suffix}"
        if status in ("fail", "error"):
            return f"[red]{status}[/red]{suffix}"
        if status == "skipped":
            return f"[dim]skip[/dim]{suffix}"
        if status is None and skipped == "prior success":
            return f"[green]prior[/green]{suffix}"
        if status is None and skipped:
            return f"[dim]skip[/dim]{suffix}"
        return f"[dim]—[/dim]{suffix}"

    return _render(comp_data.get("binary_test")), _render(comp_data.get("source_build"))


def _bytecode_cell(comp_data: dict | None) -> str:
    """Return the Bytecode cell Rich markup for a smelt component entry.

    Shows ``own → effective`` when a dependency lifts the floor above the
    component's own bytecode (the effective value highlighted), a single number
    when they agree, or ``—`` when no bytecode data is available (e.g. the
    component was skipped or errored without analysis).
    """
    if comp_data is None:
        return "[dim]—[/dim]"
    own = comp_data.get("own_bytecode")
    eff = comp_data.get("effective_bytecode")
    if own is None and eff is None:
        return "[dim]—[/dim]"
    if own is None:
        return str(eff)
    if eff is None or eff == own:
        return str(own)
    return f"{own} [dim]→[/dim] [yellow]{eff}[/yellow]"


def _print_status_table(
    entries: list[StatusEntry],
    smelt: dict[str, dict] | None = None,
) -> None:
    table = Table(title="BOM Status", show_lines=False)
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Release", justify="right")
    table.add_column("Drift", justify="right")
    table.add_column("Action", justify="left")
    if smelt is not None:
        table.add_column("Bytecode", justify="center")
        table.add_column("Binary", justify="center")
        table.add_column("Source", justify="center")

    for e in entries:
        latest = e.latest_version or e.bom_version
        if latest == e.bom_version:
            release_str = e.bom_version
        else:
            release_str = f"{e.bom_version} → {latest}"
        drift_str = drift_text(e)
        if drift_str == "—":
            drift_cell = "[dim]—[/dim]"
        elif drift_str == "???":
            drift_cell = "[dim]???[/dim]"
        else:
            drift_cell = drift_str
        action_str = {
            "Cut": "[red]Cut[/red]",
            "Bump": "[yellow]Bump[/yellow]",
            "None": "[dim]—[/dim]",
        }[e.action]
        row: list[str] = [
            f"{e.component.group}:{e.component.name}",
            release_str,
            drift_cell,
            action_str,
        ]
        if smelt is not None:
            ga = f"{e.component.group}:{e.component.name}"
            comp_data = smelt.get(ga)
            binary_cell, source_cell = _smelt_cells(comp_data, e.bom_version)
            row.extend([_bytecode_cell(comp_data), binary_cell, source_cell])
        table.add_row(*row)

    console.print(table)

    if smelt is not None and any(
        smelt.get(f"{e.component.group}:{e.component.name}", {}).get("version")
        not in (None, e.bom_version)
        for e in entries
    ):
        console.print(
            "[dim][yellow]*[/yellow] smelt result is from a different version[/dim]"
        )
