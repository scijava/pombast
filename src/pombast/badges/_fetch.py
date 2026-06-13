"""Fetch GitHub Actions CI badge status by parsing badge SVG titles."""

from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_TITLE_RE = re.compile(r"<title>([^<]*)</title>")
_DEFAULT_WORKFLOWS = ("build.yml",)


def _has_yaml_ext(name: str) -> bool:
    return name.endswith(".yml") or name.endswith(".yaml")


def _ensure_yaml_ext(name: str) -> str:
    return name if _has_yaml_ext(name) else name + ".yml"


def _fetch_svg_title(url: str) -> str | None:
    """Fetch a badge SVG URL and return its <title> text, or None on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pombast"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        m = _TITLE_RE.search(body)
        return m.group(1) if m else None
    except Exception:
        return None


def fetch_badge_title(slug: str, workflow: str | None) -> tuple[str, str] | None:
    """Fetch the badge title for a GitHub repo slug.

    If *workflow* is given (with or without extension) that workflow is used.
    Otherwise tries build.yml.

    Returns (title, resolved_workflow_filename) or None on failure.
    """
    if workflow:
        wf = _ensure_yaml_ext(workflow)
        title = _fetch_svg_title(
            f"https://github.com/{slug}/actions/workflows/{wf}/badge.svg"
        )
        return (title, wf) if title is not None else None

    last: tuple[str, str] | None = None
    for wf in _DEFAULT_WORKFLOWS:
        title = _fetch_svg_title(
            f"https://github.com/{slug}/actions/workflows/{wf}/badge.svg"
        )
        if title is not None:
            return (title, wf)
    return last


def fetch_badges(
    repos: dict[str, str | None],
    workers: int = 8,
) -> dict[str, dict]:
    """Fetch badge titles for all repos in parallel.

    *repos* maps slug → workflow override (or None for default discovery).
    Returns slug → {"title": ..., "workflow": ...} for repos that responded.
    """
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures: list[tuple[str, Future[tuple[str, str] | None]]] = [
            (slug, pool.submit(fetch_badge_title, slug, workflow))
            for slug, workflow in repos.items()
        ]
        for slug, future in futures:
            result = future.result()
            if result is not None:
                title, resolved_wf = result
                results[slug] = {"title": title, "workflow": resolved_wf}

    return results


def write_badges_json(badges: dict[str, dict], path: Path) -> None:
    """Write badges dict to a JSON file."""
    data = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repos": badges,
    }
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )
