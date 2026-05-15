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

from pombast.core._filter import ComponentFilter
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
    "--badges",
    default=None,
    help="Path to CI badge HTML overrides file (slug <space> HTML per line).",
)
@click.option(
    "--timestamps",
    default=None,
    help="Path to vetting timestamps file (G:A <space> YYYYMMDDHHmmss per line).",
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
    rules: str | None,
    projects: str | None,
    badges: str | None,
    timestamps: str | None,
    no_timestamps: bool,
    nexus_base: str | None,
    html_path: Path | None,
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

    effective_max_age = 0 if refresh else max_age

    console.print(f"[bold]BOM:[/bold] [cyan]{bom}[/cyan]")
    # User-specified repos come first; load_bom appends central as the last resort.
    repos = {}
    for i, spec in enumerate(repository):
        name, sep, url = spec.partition("=")
        if sep:
            repos[name] = url
        else:
            repos[f"repo{i}"] = spec

    bom_data = load_bom(bom, repositories=repos)
    console.print(f"Loaded [bold]{len(bom_data.components)}[/bold] components.")
    if effective_max_age:
        console.print(
            f"Metadata cache TTL: [bold]{effective_max_age // 3600}h "
            f"{(effective_max_age % 3600) // 60}m[/bold]  "
            f"(use [bold]--refresh[/bold] to bypass)"
        )

    if rules:
        console.print(f"Loading rules: [cyan]{rules}[/cyan]")
        rules_xml = RulesXML.load(rules)
    else:
        rules_xml = RulesXML.empty()

    proj_ov = load_kv_file(projects) if projects else {}
    badge_ov = load_kv_file(badges) if badges else {}
    vetting_ov = load_timestamps_file(timestamps) if timestamps else {}

    cf = ComponentFilter(includes=list(include), excludes=list(exclude))
    total = len(cf.filter(bom_data.components))

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
            badge_overrides=badge_ov,
            vetting_overrides=vetting_ov,
            includes=list(include),
            excludes=list(exclude),
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

    _print_status_table(entries)

    cuts = sum(1 for e in entries if e.action == "Cut")
    bumps = sum(1 for e in entries if e.action == "Bump")
    console.print(
        f"\n[bold]Summary:[/bold] "
        f"[red]Cut {cuts}[/red]  "
        f"[yellow]Bump {bumps}[/yellow]  "
        f"[dim]None {len(entries) - cuts - bumps}[/dim]"
    )

    if html_path:
        footer_html = footer.read_text() if footer else ""
        html_path.write_text(
            generate_html(entries, nexus_base=nexus_base or "", footer_html=footer_html)
        )
        console.print(f"HTML report written to: [cyan]{html_path}[/cyan]")


def _print_status_table(entries: list[StatusEntry]) -> None:
    table = Table(title="BOM Status", show_lines=False)
    table.add_column("Component", style="cyan", no_wrap=True)
    table.add_column("Release", justify="right")
    table.add_column("Drift", justify="right")
    table.add_column("Action", justify="left")

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
        table.add_row(
            f"{e.component.group}:{e.component.name}",
            release_str,
            drift_cell,
            action_str,
        )

    console.print(table)
