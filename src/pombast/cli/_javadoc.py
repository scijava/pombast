"""pombast javadoc subcommand."""

from __future__ import annotations

import logging
from pathlib import Path

import rich_click as click
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from pombast.config._settings import PombastConfig, parse_repo_spec
from pombast.javadoc._pipeline import JavadocPipeline, JavadocRunConfig
from pombast.javadoc._union import REDIRECT_FORMATS
from pombast.util._console import make_console

console = make_console()


@click.command("javadoc")
@click.argument("bom", default=".")
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
    help="Additional remote Maven repository URL (repeatable). Optionally prefix with name=URL.",
)
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to pombast.toml configuration file.",
)
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Javadoc site output directory (default: [javadoc] output, else target/javadoc).",
)
@click.option(
    "--url-prefix",
    default=None,
    help="Absolute URL prefix for the deployed site (e.g. https://javadoc.scijava.org).",
)
@click.option(
    "--redirect-format",
    type=click.Choice(REDIRECT_FORMATS),
    default=None,
    help="How to render the BOM union redirects (default: rewritemap).",
)
@click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of parallel download/unpack workers (default: 8).",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Re-extract components even if already unpacked.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
def javadoc_cmd(
    bom: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    repository: tuple[str, ...],
    config: Path | None,
    output_dir: Path | None,
    url_prefix: str | None,
    redirect_format: str | None,
    workers: int | None,
    force: bool,
    verbose: bool,
) -> None:
    """Generate a browsable javadoc site from a BOM's -javadoc JARs.

    Unpacks the ``-javadoc`` classifier JAR of each managed component into
    ``{output}/{g}/{a}/{v}/`` and assembles a unioned index for the BOM itself
    at ``{output}/{bom-g}/{bom-a}/{bom-v}/`` — a single, fast ``javadoc -link``
    target whose class URLs 301-redirect to the owning component.

    Compose across BOM versions by invoking once per BOM; component javadoc is
    cached per G:A:V and re-used across runs.

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pombast_config = PombastConfig.load_default(config)
    jc = pombast_config.javadoc

    repos = {
        **pombast_config.repositories,
        **{
            k: v
            for i, spec in enumerate(repository)
            for k, v in [parse_repo_spec(spec, f"repo{i}")]
        },
    }

    run_config = JavadocRunConfig(
        bom=bom,
        output_dir=output_dir or jc.output or Path("target/javadoc"),
        includes=list(include) or jc.includes,
        excludes=list(exclude) or jc.excludes,
        repositories=repos,
        url_prefix=url_prefix if url_prefix is not None else jc.url_prefix,
        redirect_format=redirect_format or jc.redirect_format,
        workers=workers if workers is not None else jc.workers,
        force=force,
    )

    console.print(f"[bold]BOM:[/bold] [cyan]{bom}[/cyan]")
    console.print(f"Output: [cyan]{run_config.output_dir}[/cyan]")

    pipeline = JavadocPipeline(run_config)

    # We don't know the component count until load_bom runs inside the pipeline,
    # so drive an indeterminate bar and let each unpack advance it.
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Unpacking…", total=None)

        def _on_unpack(result) -> None:
            progress.update(
                task, advance=1, description=result.component.coordinate
            )

        report = pipeline.run(progress=_on_unpack)

    console.print()
    console.print(
        f"Unpacked: [green]{len(report.unpacked)}[/green]  "
        f"Cached: [cyan]{len(report.cached)}[/cyan]  "
        f"Missing: [yellow]{len(report.missing)}[/yellow]  "
        f"Errors: [red]{len(report.errors)}[/red]"
    )
    if report.union is not None:
        u = report.union
        console.print(
            f"Union [bold]{report.bom.coordinate}[/bold]: "
            f"{u.package_count} packages, {u.redirect_count} redirects "
            f"from {u.component_count} components."
        )
        console.print(f"Wrote site to: [cyan]{run_config.output_dir}[/cyan]")
