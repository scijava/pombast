"""Command-line interface for pombast."""

from __future__ import annotations

import rich_click as click

# Rich expands ``:word:`` into emoji by default, which mangles Maven coordinates
# in help text (e.g. ``sc.fiji:fiji:2.17.0`` → ``sc.fiji🇫🇯2.17.0``). Disable it
# globally before any command module renders help. See also util._console.
click.rich_click.USE_MARKDOWN_EMOJI = False
