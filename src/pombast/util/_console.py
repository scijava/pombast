"""Shared Rich console factory."""

from __future__ import annotations

from typing import Any

from rich.console import Console


def make_console(**kwargs: Any) -> Console:
    """Construct a Rich ``Console`` with emoji substitution disabled.

    Rich expands ``:word:`` patterns into emoji by default, which mangles Maven
    coordinates: ``sc.fiji:fiji:2.17.0`` renders as ``sc.fiji🇫🇯2.17.0`` because
    ``:fiji:`` matches the Fiji flag emoji code. We never emit emoji, so disable
    the behavior everywhere. Callers may still override via ``emoji=True``.
    """
    kwargs.setdefault("emoji", False)
    return Console(**kwargs)
