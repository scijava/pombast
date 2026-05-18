"""Command-line interface for pombast."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.table import Table

from pombast import __version__
from pombast.config._settings import PipelineConfig, PombastConfig
from pombast.core._component import BuildStatus
from pombast.core._pipeline import Pipeline

console = Console()


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """pombast — validate and monitor Maven BOM components."""


@cli.command("validate")
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
    help="Path to pombast.toml configuration file.",
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default="pombast-output",
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
    "--mega-melt-only",
    is_flag=True,
    help="Run mega-melt BOM validation only; skip per-component builds.",
)
@click.option(
    "--no-mega-melt",
    is_flag=True,
    help="Skip mega-melt BOM validation; run only per-component builds.",
)
@click.option(
    "--no-binary-test",
    is_flag=True,
    help="Skip binary compatibility testing (only rebuild from source).",
)
@click.option(
    "--min-java",
    type=int,
    default=None,
    help="Minimum Java version floor for all components (e.g., 11).",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
def validate_cmd(
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
    mega_melt_only: bool,
    no_mega_melt: bool,
    no_binary_test: bool,
    min_java: int | None,
    verbose: bool,
) -> None:
    """Validate that BOM components actually work together.

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pombast_config = PombastConfig.load(config) if config else PombastConfig.empty()
    effective_min_java = min_java or pombast_config.min_java_version
    effective_repositories = pombast_config.repositories + list(repository)

    pipeline_config = PipelineConfig(
        bom=bom,
        min_java_version=effective_min_java,
        changes=list(change),
        includes=list(include),
        excludes=list(exclude),
        repositories=effective_repositories,
        output_dir=output_dir,
        prune=prune,
        force=force,
        skip_build=skip_build,
        mega_melt_only=mega_melt_only,
        no_mega_melt=no_mega_melt,
        mega_melt_java_version=pombast_config.mega_melt.java_version,
        mega_melt_template=pombast_config.mega_melt.template,
        test_binary=not no_binary_test,
        verbose=verbose,
        config=pombast_config,
    )

    console.print(f"[bold]pombast {__version__}[/bold]")
    console.print(f"Validating BOM: [cyan]{bom}[/cyan]")

    pipeline = Pipeline(pipeline_config)
    report = pipeline.run()

    if report.mega_melt_success is not None:
        if report.mega_melt_success:
            console.print("[green]Mega-melt: PASSED[/green]")
        else:
            console.print("[red]Mega-melt: FAILED[/red]")
            if report.mega_melt_build_log:
                console.print(f"  See: {report.mega_melt_build_log}")

    if report.results:
        _print_results_table(report)

    console.print()
    console.print(report.summary())

    mega_melt_failed = 1 if report.mega_melt_success is False else 0
    failures = mega_melt_failed + len(report.failures) + len(report.errors)
    sys.exit(min(failures, 254))


@cli.command("melt")
@click.argument("bom")
@click.option(
    "-i",
    "--include",
    multiple=True,
    help="G:A pattern to include in mega-melt (repeatable, wildcards OK).",
)
@click.option(
    "-e",
    "--exclude",
    multiple=True,
    help="G:A pattern to exclude from mega-melt (repeatable, wildcards OK).",
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
    help="Path to pombast.toml configuration file.",
)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(path_type=Path),
    default="pombast-output",
    help="Output directory.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Wipe output directory if it exists.",
)
@click.option(
    "--min-java",
    type=int,
    default=None,
    help="Minimum Java version floor (e.g., 11).",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
def melt_cmd(
    bom: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    repository: tuple[str, ...],
    config: Path | None,
    output_dir: Path,
    force: bool,
    min_java: int | None,
    verbose: bool,
) -> None:
    """Run mega-melt BOM validation only (no per-component builds).

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pombast_config = PombastConfig.load(config) if config else PombastConfig.empty()
    effective_min_java = min_java or pombast_config.min_java_version
    effective_repositories = pombast_config.repositories + list(repository)

    pipeline_config = PipelineConfig(
        bom=bom,
        min_java_version=effective_min_java,
        includes=[],
        excludes=[],
        repositories=effective_repositories,
        output_dir=output_dir,
        force=force,
        mega_melt_only=True,
        mega_melt_includes=list(include),
        mega_melt_excludes=list(exclude),
        mega_melt_java_version=pombast_config.mega_melt.java_version,
        mega_melt_template=pombast_config.mega_melt.template,
        verbose=verbose,
        config=pombast_config,
    )

    console.print(f"[bold]pombast {__version__}[/bold]")
    console.print(f"Mega-melt validation: [cyan]{bom}[/cyan]")

    pipeline = Pipeline(pipeline_config)
    report = pipeline.run()

    if report.mega_melt_success is not None:
        if report.mega_melt_success:
            console.print("[green]Mega-melt: PASSED[/green]")
        else:
            console.print("[red]Mega-melt: FAILED[/red]")
            if report.mega_melt_build_log:
                console.print(f"  See: {report.mega_melt_build_log}")

    console.print()
    console.print(report.summary())

    sys.exit(0 if report.mega_melt_success is not False else 1)


def _print_results_table(report) -> None:
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
            f"{result.duration_seconds:.1f}s" if result.duration_seconds > 0 else "-"
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
