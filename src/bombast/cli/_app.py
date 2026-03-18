"""Command-line interface for bombast."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.table import Table

from bombast import __version__
from bombast.config._settings import BombastConfig, PipelineConfig
from bombast.core._component import BuildStatus
from bombast.core._pipeline import Pipeline

console = Console()


@click.command()
@click.argument("bom")
@click.option(
    "-c",
    "--change",
    multiple=True,
    help="G:A:V to inject as a version override (repeatable).",
)
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
    help="Additional remote Maven repository URL (repeatable).",
)
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to bombast.toml configuration file.",
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default="bombast-output",
    help="Output directory.",
)
@click.option(
    "-p",
    "--prune",
    is_flag=True,
    help="Only build components that depend on changed artifacts.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Wipe output directory if it exists.",
)
@click.option(
    "-s",
    "--skip-build",
    is_flag=True,
    help="Prepare everything but skip actual builds.",
)
@click.option(
    "--no-binary-test",
    is_flag=True,
    help="Skip binary compatibility testing (only rebuild from source).",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
@click.version_option(version=__version__)
@click.pass_context
def cli(
    ctx: click.Context,
    bom: str,
    change: tuple[str, ...],
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    repository: tuple[str, ...],
    config: Path | None,
    output_dir: Path,
    prune: bool,
    force: bool,
    skip_build: bool,
    no_binary_test: bool,
    verbose: bool,
) -> None:
    """Validate that BOM components actually work together.

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    # Configure logging.
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Load config file if provided.
    bombast_config = BombastConfig.load(config) if config else BombastConfig.empty()

    # Build pipeline config.
    pipeline_config = PipelineConfig(
        bom=bom,
        changes=list(change),
        includes=list(include),
        excludes=list(exclude),
        repositories=list(repository),
        output_dir=output_dir,
        prune=prune,
        force=force,
        skip_build=skip_build,
        test_binary=not no_binary_test,
        verbose=verbose,
        config=bombast_config,
    )

    console.print(f"[bold]bombast {__version__}[/bold]")
    console.print(f"Validating BOM: [cyan]{bom}[/cyan]")

    # Run the pipeline.
    pipeline = Pipeline(pipeline_config)
    report = pipeline.run()

    # Print results table.
    if report.results:
        _print_results_table(report)

    console.print()
    console.print(report.summary())

    # Exit with failure count (capped at 254, 255 reserved).
    failures = len(report.failures) + len(report.errors)
    sys.exit(min(failures, 254))


def _print_results_table(report) -> None:
    """Print a Rich table summarizing build results."""
    table = Table(title="Build Results")
    table.add_column("Component", style="cyan")
    table.add_column("Binary")
    table.add_column("Source")
    table.add_column("Duration", justify="right")
    table.add_column("Note")

    status_styles = {
        BuildStatus.SUCCESS: "[green]SUCCESS[/green]",
        BuildStatus.FAILURE: "[red]FAILURE[/red]",
        BuildStatus.ERROR: "[red]ERROR[/red]",
        BuildStatus.SKIPPED: "[yellow]SKIPPED[/yellow]",
        None: "-",
    }

    for result in report.results:
        duration = (
            f"{result.duration_seconds:.1f}s"
            if result.duration_seconds > 0
            else "-"
        )
        note = result.skipped_reason or ""
        table.add_row(
            result.component.coordinate,
            status_styles.get(result.binary_status, "-"),
            status_styles.get(result.status, str(result.status)),
            duration,
            note,
        )

    console.print(table)
