"""Tests for status CLI rendering helpers."""

from pombast.cli._status import _bytecode_cell


class TestBytecodeCell:
    def test_no_data(self):
        assert _bytecode_cell(None) == "[dim]—[/dim]"

    def test_missing_both_fields(self):
        assert _bytecode_cell({"version": "1.0.0"}) == "[dim]—[/dim]"

    def test_equal_own_and_effective(self):
        cell = _bytecode_cell({"own_bytecode": 17, "effective_bytecode": 17})
        assert cell == "17"

    def test_lifted_effective(self):
        cell = _bytecode_cell({"own_bytecode": 8, "effective_bytecode": 21})
        assert cell == "8 [dim]→[/dim] [yellow]21[/yellow]"

    def test_only_effective(self):
        cell = _bytecode_cell({"effective_bytecode": 11})
        assert cell == "11"

    def test_only_own(self):
        cell = _bytecode_cell({"own_bytecode": 11})
        assert cell == "11"
