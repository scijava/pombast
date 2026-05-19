"""Serialize a ValidationReport to a stable JSON structure."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.core._component import BuildResult, BuildStatus, ValidationReport

_SCHEMA_VERSION = 1
_TAIL_LINES = 50
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _tail_log(log_path: Path | None, n: int = _TAIL_LINES) -> str | None:
    if log_path is None or not log_path.exists():
        return None
    text = _strip_ansi(log_path.read_text(errors="replace"))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-n:]) if lines else None


def _status_str(status: BuildStatus | None) -> str | None:
    if status is None:
        return None
    from pombast.core._component import BuildStatus

    return {
        BuildStatus.SUCCESS: "pass",
        BuildStatus.FAILURE: "fail",
        BuildStatus.ERROR: "error",
        BuildStatus.SKIPPED: "skipped",
    }[status]


def _is_failing(status: BuildStatus | None) -> bool:
    if status is None:
        return False
    from pombast.core._component import BuildStatus

    return status in (BuildStatus.FAILURE, BuildStatus.ERROR)


def _component_entry(result: BuildResult) -> dict:
    binary_str = _status_str(result.binary_status)
    source_str = _status_str(result.status)
    return {
        "version": result.component.version,
        "binary_test": binary_str,
        "source_build": source_str,
        "skipped_reason": result.skipped_reason,
        "binary_log": _tail_log(result.binary_log_path)
        if _is_failing(result.binary_status)
        else None,
        "source_log": _tail_log(result.log_path)
        if _is_failing(result.status)
        else None,
    }


def report_to_dict(report: ValidationReport) -> dict:
    """Convert a ValidationReport to a stable, JSON-serialisable dict."""
    components = {
        result.component.ga: _component_entry(result) for result in report.results
    }
    return {
        "version": _SCHEMA_VERSION,
        "bom": report.bom,
        "components": components,
    }


def write_json(report: ValidationReport, path: Path) -> None:
    """Write report as pretty-printed JSON to path."""
    data = report_to_dict(report)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
