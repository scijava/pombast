"""Main entry point for bombast CLI."""

from bombast.cli._app import cli
from bombast.cli._status import status_cmd

cli.add_command(status_cmd)


def main():
    """Main entry point for the bombast CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
