"""Command-line interface for bombast."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from bombast import __version__


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
    verbose: bool,
) -> None:
    """Validate that BOM components actually work together.

    BOM is a Maven G:A:V coordinate or a local directory path.
    """
    click.echo(f"bombast {__version__}")
    click.echo(f"Validating BOM: {bom}")
    # TODO: Wire up to Pipeline once implemented.
