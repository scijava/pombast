"""pombast badges subcommand."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

import rich_click as click
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from pombast.badges._fetch import fetch_badge_title, write_badges_json
from pombast.config._settings import PombastConfig, parse_repo_spec
from pombast.core._filter import ComponentFilter
from pombast.maven._bom import load_bom
from pombast.status._query import _infer_project_url, _scm_project_url, load_kv_file
from pombast.util._console import make_console

console = make_console()


@click.command("badges")
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
    "--projects",
    default=None,
    help="Path to project URL overrides file (G:A <space> URL per line).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default="badges.json",
    show_default=True,
    help="Output JSON file path.",
)
@click.option(
    "--workers",
    default=8,
    show_default=True,
    type=int,
    help="Number of parallel HTTP workers.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
def badges_cmd(
    bom: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    repository: tuple[str, ...],
    config: Path | None,
    projects: str | None,
    output_path: Path,
    workers: int,
    verbose: bool,
) -> None:
    """Fetch GitHub Actions CI badge status for BOM components.

    Fetches each component's badge SVG, extracts the status title, and writes
    a badges.json file suitable for use with the pombast status HTML report.

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    pombast_config = PombastConfig.load_default(config)
    sc = pombast_config.status
    effective_projects = projects or (str(sc.projects) if sc.projects else None)

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

    proj_ov = load_kv_file(effective_projects) if effective_projects else {}
    comp_ov = pombast_config.component_overrides

    bc = pombast_config.badges
    cf = ComponentFilter(
        includes=list(include) or bc.includes,
        excludes=list(exclude) or bc.excludes,
    )
    components = cf.filter(bom_data.components)

    ctx = bom_data.ctx
    repo_map: dict[str, str | None] = {}
    for comp in components:
        g, a = comp.group, comp.name
        comp_data = comp_ov.get(f"{g}:{a}", {})
        _pu = comp_data.get("project-url")
        url = (
            (str(_pu) if isinstance(_pu, str) else "")
            or proj_ov.get(f"{g}:{a}")
            or _scm_project_url(ctx, g, a, comp.version)
            or _infer_project_url(g, a)
        )
        if not url or not url.startswith("https://github.com/"):
            continue
        slug = url[len("https://github.com/") :]
        ci_build = comp_data.get("ci-build")
        if ci_build is False:
            continue  # ci-build = false suppresses the badge
        workflow: str | None = ci_build if isinstance(ci_build, str) else None
        repo_map[slug] = workflow

    total = len(repo_map)
    console.print(f"Fetching badges for [bold]{total}[/bold] repos…")

    badges: dict[str, dict] = {}
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching…", total=total)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures: dict[Future[tuple[str, str] | None], str] = {
                pool.submit(fetch_badge_title, slug, workflow): slug
                for slug, workflow in repo_map.items()
            }
            for future in as_completed(futures):
                slug = futures[future]
                result = future.result()
                if result is not None:
                    title, resolved_wf = result
                    badges[slug] = {"title": title, "workflow": resolved_wf}
                progress.update(task, advance=1, description=slug)

    write_badges_json(badges, output_path)
    console.print(
        f"[bold]{len(badges)}[/bold] badges written to [cyan]{output_path}[/cyan]."
    )
