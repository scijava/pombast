"""Shared helpers for rendering vetted/updated drift."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pombast.status._entry import StatusEntry


def format_duration(seconds: int) -> str:
    """Render a non-negative duration in seconds as a compact human string."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    days = hours // 24
    if days < 14:
        return f"{days}d"
    if days < 60:
        return f"{days // 7}w"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def drift_text(entry: StatusEntry) -> str:
    """Render the Drift cell as a plain-text label.

    Returns "???" if either timestamp is missing, "—" if mainline is fully
    caught up with the last vetting, or a compact duration otherwise.
    """
    lv = entry.last_vetted
    lu = entry.last_updated
    if lv is None or lu is None:
        return "???"
    delta = int((lu - lv).total_seconds())
    if delta <= 0:
        return "—"
    return format_duration(delta)
