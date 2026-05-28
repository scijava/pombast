"""pombast team subcommand."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

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
from pombast.maven._bom import load_bom
from pombast.maven._rules import RulesXML
from pombast.status._query import (
    DEFAULT_MAX_AGE,
    load_kv_file,
    load_timestamps_file,
    query_status,
)
from pombast.team._github import fetch_repo_stats
from pombast.team._html import generate_team_html
from pombast.team._pom_devs import fetch_developers
from pombast.team._workload import build_workloads

console = Console()


@click.command("team")
@click.argument("bom")
@click.option(
    "--token",
    envvar="GITHUB_TOKEN",
    default=None,
    help="GitHub personal access token (or set GITHUB_TOKEN). Required for issue/PR data.",
)
@click.option(
    "-r",
    "--repository",
    multiple=True,
    help="Additional remote Maven repository (repeatable). Optionally prefix with name=URL.",
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
    help="Path or URL to versions-maven-plugin rules.xml.",
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
    "--max-age",
    default=DEFAULT_MAX_AGE,
    show_default=True,
    type=int,
    help="Re-fetch maven-metadata.xml only if cached copy is older than this many seconds.",
)
@click.option(
    "--refresh",
    is_flag=True,
    help="Ignore all Maven metadata caches and fetch fresh data.",
)
@click.option(
    "--workers",
    default=8,
    show_default=True,
    type=int,
    help="Number of parallel HTTP workers for Maven queries.",
)
@click.option(
    "--html",
    "html_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write HTML team report to this file.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
def team_cmd(
    bom: str,
    token: str | None,
    repository: tuple[str, ...],
    config: Path | None,
    rules: str | None,
    projects: str | None,
    timestamps: str | None,
    max_age: int,
    refresh: bool,
    workers: int,
    html_path: Path | None,
    verbose: bool,
) -> None:
    """Show team accountability status for all BOM component developers.

    BOM is a Maven G:A:V coordinate or a local directory path.

    For each developer listed in component POMs, shows their current workload
    by role: PRs to review, issues to answer, bugs to fix, features requested,
    and components needing a release. Useful for identifying who needs follow-up.

    Requires a GitHub token to fetch issue/PR data. Pass --token or set the
    GITHUB_TOKEN environment variable.
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
    effective_max_age = 0 if refresh else max_age

    repos = {
        **pombast_config.repositories,
        **{
            k: v
            for i, spec in enumerate(repository)
            for k, v in [parse_repo_spec(spec, f"repo{i}")]
        },
    }
    repos.setdefault("central", "https://repo1.maven.org/maven2")

    console.print(f"[bold]BOM:[/bold] [cyan]{bom}[/cyan]")
    bom_data = load_bom(bom, repositories=repos)
    console.print(f"Loaded [bold]{len(bom_data.components)}[/bold] components.")

    rules_xml = RulesXML.load(effective_rules) if effective_rules else RulesXML.empty()
    proj_ov = load_kv_file(effective_projects) if effective_projects else {}
    vetting_ov = (
        load_timestamps_file(effective_timestamps) if effective_timestamps else {}
    )

    # Phase 1: query Maven release status (same data as `pombast status`)
    console.print("\n[bold]Phase 1:[/bold] Querying Maven release status…")
    entries = []
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Maven…", total=len(bom_data.components))
        for entry in query_status(
            bom_data,
            rules=rules_xml,
            project_overrides=proj_ov,
            vetting_overrides=vetting_ov,
            fetch_timestamps=True,
            workers=workers,
            max_age=effective_max_age or None,
        ):
            entries.append(entry)
            progress.update(
                task,
                advance=1,
                description=f"{entry.component.group}:{entry.component.name}",
            )
    console.print(f"  {len(entries)} components queried.")

    # Phase 2: fetch developer roles from component POMs
    console.print(
        "\n[bold]Phase 2:[/bold] Fetching developer metadata from component POMs…"
    )
    dev_roles: dict[str, list] = {}
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("POMs…", total=len(entries))
        for entry in entries:
            g, a = entry.component.group, entry.component.name
            v = entry.latest_version or entry.bom_version
            ga = f"{g}:{a}"
            devs = fetch_developers(bom_data.ctx, g, a, v, repos)
            if devs:
                dev_roles[ga] = devs
            progress.update(task, advance=1, description=ga)
    developer_count = len({dev.id for devs in dev_roles.values() for dev, _ in devs})
    console.print(
        f"  Found {developer_count} unique developers across {len(dev_roles)} components."
    )

    # Phase 3: fetch GitHub issue/PR stats per repo
    if not token:
        console.print(
            "\n[yellow]Warning:[/yellow] No GitHub token — skipping issue/PR data. "
            "Pass [bold]--token[/bold] or set [bold]GITHUB_TOKEN[/bold]."
        )
        repo_stats: dict = {}
    else:
        team_cfg = pombast_config.team
        team_filter = ComponentFilter(
            includes=team_cfg.includes, excludes=team_cfg.excludes
        )
        orgs: set[str] = set()
        for e in entries:
            if not team_filter.is_included(e.component):
                continue
            url = e.project_url or ""
            parts = url.split("/")
            if "github.com" in url and len(parts) >= 5:
                orgs.add(parts[3])

        console.print(
            f"\n[bold]Phase 3:[/bold] Fetching GitHub data for "
            f"[bold]{len(orgs)}[/bold] org(s): {', '.join(sorted(orgs))}"
        )
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as gh_progress:
            task = gh_progress.add_task("GitHub…", total=None)

            def _gh_progress(fetched: int, total: int) -> None:
                gh_progress.update(task, completed=fetched, total=total)

            repo_stats = fetch_repo_stats(
                orgs,
                token=token,
                refresh=refresh,
                progress=_gh_progress,
            )
        console.print(f"  Got stats for {len(repo_stats)} repos.")

    # Phase 4: aggregate and display
    workload_rows = build_workloads(entries, dev_roles, repo_stats, pombast_config)

    table = Table(title="Team Workload", show_lines=False)
    table.add_column("Developer", style="cyan", no_wrap=True)
    table.add_column("PRs", justify="right", header_style="", style="", no_wrap=True)
    table.add_column("Issues", justify="right", no_wrap=True)
    table.add_column("Bugs", justify="right", no_wrap=True)
    table.add_column("Features", justify="right", no_wrap=True)
    table.add_column("Releases", justify="right", no_wrap=True)
    table.add_column("Total", justify="right", style="bold", no_wrap=True)
    table.add_column("Components", justify="right", no_wrap=True)

    def _cell(n: int, style: str = "red") -> str:
        return f"[{style}]{n}[/{style}]" if n > 0 else "[dim]0[/dim]"

    for row in workload_rows:
        dev = row.developer
        table.add_row(
            dev.name or dev.id,
            _cell(row.reviewer_prs),
            _cell(row.support_issues),
            _cell(row.debugger_bugs),
            _cell(row.developer_features),
            _cell(row.maintainer_releases),
            str(row.total),
            str(len(row.components)),
        )

    console.print()
    console.print(table)

    if html_path:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        html_path.write_text(generate_team_html(workload_rows, generated=generated))
        console.print(f"\nHTML team report written to: [cyan]{html_path}[/cyan]")
