"""Serialize a ValidationReport to a stable JSON structure."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.core._component import BuildResult, BuildStatus, ValidationReport

_SCHEMA_VERSION = 1
_FALLBACK_TAIL = 50
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _extract_log(log_path: Path | None) -> str | None:
    """Return error lines from a Maven log, falling back to the last N lines.

    Filters to lines whose ANSI-stripped form starts with [ERROR] (Maven's
    standard error marker), preserving ANSI codes in the returned content so
    the browser can render colors via ansi_up or similar.  Falls back to the
    last _FALLBACK_TAIL non-empty lines when no [ERROR] lines are present, so
    failures without [ERROR] output still surface something.
    """
    if log_path is None or not log_path.exists():
        return None
    lines = log_path.read_text(errors="replace").splitlines()
    error_lines = [ln for ln in lines if _strip_ansi(ln).startswith("[ERROR]")]
    if error_lines:
        return "\n".join(error_lines)
    non_empty = [ln for ln in lines if ln.strip()]
    return "\n".join(non_empty[-_FALLBACK_TAIL:]) if non_empty else None


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
        "binary_log": _extract_log(result.binary_log_path)
        if _is_failing(result.binary_status)
        else None,
        "source_log": _extract_log(result.log_path)
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


def load_smelt_components(path: Path) -> dict[str, dict]:
    """Load smelt.json, returning a mapping of G:A to per-component data."""
    with open(path) as f:
        data = json.load(f)
    return data.get("components", {})
