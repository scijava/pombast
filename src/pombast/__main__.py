"""Main entry point for pombast CLI."""

from pombast.cli._app import cli
from pombast.cli._status import status_cmd

cli.add_command(status_cmd)


def main():
    """Main entry point for the pombast CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
