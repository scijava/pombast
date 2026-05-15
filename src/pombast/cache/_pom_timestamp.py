"""Persistent cache for release POM Last-Modified timestamps."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "pombast" / "pom-timestamps"


class PomTimestampCache:
    """Caches the Last-Modified timestamp of release POM files.

    A released POM never changes, so these entries have no expiry.
    Each entry is stored as a plain ISO-format datetime string at
    {cache_dir}/{g/path}/{artifactId}/{version}.
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR

    def _path(self, group_id: str, artifact_id: str, version: str) -> Path:
        g_path = group_id.replace(".", "/")
        return self.cache_dir / g_path / artifact_id / version

    def get(self, group_id: str, artifact_id: str, version: str) -> datetime | None:
        """Return the cached timestamp, or None if not cached."""
        p = self._path(group_id, artifact_id, version)
        if not p.exists():
            return None
        try:
            return datetime.fromisoformat(p.read_text().strip())
        except (ValueError, OSError):
            return None

    def put(self, group_id: str, artifact_id: str, version: str, ts: datetime) -> None:
        """Store a timestamp in the cache."""
        p = self._path(group_id, artifact_id, version)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ts.isoformat())
