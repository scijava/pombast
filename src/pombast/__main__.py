"""Main entry point for pombast CLI."""

from pombast.cli._app import cli
from pombast.cli._badges import badges_cmd
from pombast.cli._javadoc import javadoc_cmd
from pombast.cli._status import status_cmd
from pombast.cli._team import team_cmd

cli.add_command(badges_cmd)
cli.add_command(javadoc_cmd)
cli.add_command(status_cmd)
cli.add_command(team_cmd)


def main():
    """Main entry point for the pombast CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
