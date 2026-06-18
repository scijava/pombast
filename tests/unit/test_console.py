"""Tests for the shared Rich console factory."""

import io

import rich_click as click

from pombast.util._console import make_console


class TestMakeConsole:
    def test_emoji_disabled_by_default(self):
        assert make_console()._emoji is False

    def test_gav_not_mangled_to_emoji(self):
        """``:fiji:`` in a Maven coordinate must not become a flag emoji."""
        buf = io.StringIO()
        make_console(file=buf, color_system=None).print("sc.fiji:fiji:2.17.0")
        assert buf.getvalue() == "sc.fiji:fiji:2.17.0\n"

    def test_emoji_override(self):
        assert make_console(emoji=True)._emoji is True


def test_rich_click_markdown_emoji_disabled():
    """Importing the CLI package disables rich-click markdown emoji."""
    import pombast.cli  # noqa: F401

    assert click.rich_click.USE_MARKDOWN_EMOJI is False
