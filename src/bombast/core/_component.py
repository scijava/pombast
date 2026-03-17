"""Core data types for BOM validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class Component:
    """A buildable/testable unit of software managed by a BOM.

    This is ecosystem-agnostic: for Maven, group=groupId, name=artifactId.
    """

    group: str
    name: str
    version: str
    scm_url: str | None = None
    scm_tag: str | None = None
    java_version: int | None = None

    @property
    def coordinate(self) -> str:
        """Return G:A:V coordinate string."""
        return f"{self.group}:{self.name}:{self.version}"

    @property
    def ga(self) -> str:
        """Return G:A string for filtering."""
        return f"{self.group}:{self.name}"

    def __str__(self) -> str:
        return self.coordinate


class BuildStatus(Enum):
    """Outcome of building/testing a component."""

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class BuildResult:
    """Outcome of building/testing a single component."""

    component: Component
    status: BuildStatus
    log_path: Path | None = None
    duration_seconds: float = 0.0
    skipped_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in (BuildStatus.SUCCESS, BuildStatus.SKIPPED)


@dataclass
class ValidationReport:
    """Aggregate outcome of validating a BOM."""

    bom: str
    results: list[BuildResult] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @property
    def successes(self) -> list[BuildResult]:
        return [r for r in self.results if r.status == BuildStatus.SUCCESS]

    @property
    def failures(self) -> list[BuildResult]:
        return [r for r in self.results if r.status == BuildStatus.FAILURE]

    @property
    def errors(self) -> list[BuildResult]:
        return [r for r in self.results if r.status == BuildStatus.ERROR]

    @property
    def skipped(self) -> list[BuildResult]:
        return [r for r in self.results if r.status == BuildStatus.SKIPPED]

    def summary(self) -> str:
        """Return a human-readable summary string."""
        total = len(self.results)
        lines = [
            f"BOM: {self.bom}",
            f"Total: {total}",
            f"  Success: {len(self.successes)}",
            f"  Failed:  {len(self.failures)}",
            f"  Errors:  {len(self.errors)}",
            f"  Skipped: {len(self.skipped)}",
        ]
        return "\n".join(lines)
