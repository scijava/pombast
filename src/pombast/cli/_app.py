"""Command-line interface for pombast."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import rich_click as click
from rich.table import Table

from pombast import __version__
from pombast.config._settings import (
    MeltConfig,
    PipelineConfig,
    PombastConfig,
    parse_repo_spec,
)
from pombast.core._component import BuildStatus
from pombast.core._melt_pipeline import MeltPipeline
from pombast.core._pipeline import Pipeline
from pombast.util._console import make_console

console = make_console()


def _parse_defines(specs: tuple[str, ...]) -> dict[str, str]:
    """Parse KEY=VALUE strings into a dict; bare KEY maps to empty string."""
    result: dict[str, str] = {}
    for spec in specs:
        key, sep, value = spec.partition("=")
        result[key] = value if sep else ""
    return result


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """pombast — validate and monitor Maven BOM components."""


@cli.command("smelt")
@click.argument("bom", default=".")
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
    "--build-dir",
    "output_dir",
    type=click.Path(path_type=Path),
    default="pombast-output",
    help="Working directory for builds.",
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
    help="Wipe build directory if it exists.",
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
@click.option(
    "--default-java",
    type=int,
    default=None,
    help="Default Java version for components with no declared version (e.g., 11).",
)
@click.option(
    "-o",
    "--output",
    "json_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write smelt results as JSON to this file.",
)
@click.option(
    "-D",
    "--define",
    "define",
    multiple=True,
    help="Extra Maven property (KEY=VALUE, repeatable). Passed to every component build.",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose output.")
def smelt_cmd(
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
    default_java: int | None,
    json_path: Path | None,
    define: tuple[str, ...],
    verbose: bool,
) -> None:
    """Build and test each BOM component against its pinned dependencies.

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pombast_config = PombastConfig.load_default(config)
    effective_default_java = default_java or pombast_config.default_java
    effective_repositories = {
        **pombast_config.repositories,
        **{
            k: v
            for i, spec in enumerate(repository)
            for k, v in [parse_repo_spec(spec, f"repo{i}")]
        },
    }

    pipeline_config = PipelineConfig(
        bom=bom,
        default_java=effective_default_java,
        changes=list(change),
        includes=list(include),
        excludes=list(exclude),
        repositories=effective_repositories,
        output_dir=output_dir,
        prune=prune,
        force=force,
        skip_build=skip_build,
        test_binary=not no_binary_test,
        maven_properties=_parse_defines(define),
        verbose=verbose,
        config=pombast_config,
    )

    console.print(f"[bold]pombast {__version__}[/bold]")
    console.print(f"Smelting BOM: [cyan]{bom}[/cyan]")

    pipeline = Pipeline(pipeline_config)
    report = pipeline.run()

    if report.results:
        _print_results_table(report)

    console.print()
    console.print(report.summary())

    effective_json = json_path or pombast_config.smelt_output
    if effective_json:
        from pombast.core._smelt_json import write_json

        write_json(report, effective_json)
        console.print(f"JSON report written to: [cyan]{effective_json}[/cyan]")

    failures = len(report.failures) + len(report.errors)
    sys.exit(min(failures, 254))


@cli.command("melt")
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
    help="Additional remote Maven repository URL (repeatable).",
)
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to pombast.toml configuration file.",
)
@click.option(
    "--build-dir",
    "output_dir",
    type=click.Path(path_type=Path),
    default="pombast-output",
    help="Working directory for builds.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Wipe build directory if it exists.",
)
@click.option(
    "--java-version",
    type=int,
    default=None,
    help="Java version to use for mega-melt (e.g., 11).",
)
@click.option(
    "-D",
    "--define",
    "define",
    multiple=True,
    help="Extra Maven property (KEY=VALUE, repeatable). Passed to the mega-melt build.",
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
    java_version: int | None,
    define: tuple[str, ...],
    verbose: bool,
) -> None:
    """Validate the full BOM classpath as a single mega-melt project.

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pombast_config = PombastConfig.load_default(config)
    effective_java_version = java_version or pombast_config.default_java
    effective_repositories = {
        **pombast_config.repositories,
        **{
            k: v
            for i, spec in enumerate(repository)
            for k, v in [parse_repo_spec(spec, f"repo{i}")]
        },
    }

    melt_config = MeltConfig(
        bom=bom,
        repositories=effective_repositories,
        output_dir=output_dir,
        force=force,
        includes=list(include),
        excludes=list(exclude),
        default_java=effective_java_version,
        maven_properties=_parse_defines(define),
        verbose=verbose,
        config=pombast_config,
    )

    console.print(f"[bold]pombast {__version__}[/bold]")
    console.print(f"Melting BOM: [cyan]{bom}[/cyan]")

    result = MeltPipeline(melt_config).run()

    if result.success:
        console.print("[green]Mega-melt: PASSED[/green]")
    else:
        console.print("[red]Mega-melt: FAILED[/red]")
        if result.build_log:
            console.print(f"  See: {result.build_log}")

    sys.exit(0 if result.success else 1)


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
