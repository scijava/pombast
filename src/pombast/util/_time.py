"""Timezone helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(dt: datetime) -> datetime:
    """Convert dt to UTC, treating a naive datetime as already being in UTC.

    Maven timestamps are UTC, but jgo < 3.2.0 returned them naive, and older
    pombast caches hold naive values. Normalizing everything to UTC-aware keeps
    comparisons between them from raising TypeError.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
