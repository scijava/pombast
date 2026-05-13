"""Status entry for a single BOM component."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bombast.core._component import Component

_SNAPSHOT_THRESHOLD = timedelta(days=1)


@dataclass
class StatusEntry:
    """Release status of one component in the BOM."""

    component: Component
    latest_version: str | None
    release_timestamp: datetime | None  # when latest_version was released
    last_updated: datetime | None  # most recent deployment of any version
    vetting_override: datetime | None  # manual "last checked" from timestamps file
    project_url: str | None
    badge_html: str | None

    @property
    def bom_version(self) -> str:
        return self.component.version

    @property
    def last_vetted(self) -> datetime | None:
        """Most recent of release_timestamp and vetting_override."""
        candidates = [t for t in (self.release_timestamp, self.vetting_override) if t]
        return max(candidates) if candidates else None

    @property
    def bom_ok(self) -> bool:
        """True if the BOM version is current or the component has been manually vetted."""
        if self.bom_version == self.latest_version or self.latest_version is None:
            return True
        # Manual vetting counts if it is at least as recent as the last deployment.
        if (
            self.vetting_override
            and self.last_updated
            and self.vetting_override >= self.last_updated
        ):
            return True
        return False

    @property
    def release_ok(self) -> bool:
        """True if no SNAPSHOT has been deployed more than 24h after the newest release."""
        if self.release_timestamp is None or self.last_updated is None:
            return True
        if self.vetting_override and self.vetting_override >= self.last_updated:
            return True
        return (self.last_updated - self.release_timestamp) <= _SNAPSHOT_THRESHOLD

    @property
    def action(self) -> str:
        """Recommended maintenance action: 'Cut', 'Bump', or 'None'."""
        if self.project_url and not self.release_ok:
            return "Cut"
        if not self.bom_ok:
            return "Bump"
        return "None"
