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
_DEFAULT_WORKFLOWS = ("build-main.yml", "build.yml")


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


def fetch_badge_title(slug: str, workflow: str | None) -> str | None:
    """Fetch the badge title for a GitHub repo slug.

    If *workflow* is given (with or without .yml suffix) that workflow is used.
    Otherwise tries build-main.yml then build.yml, preferring whichever returns
    a status other than 'no status'.
    """
    if workflow:
        wf = workflow if workflow.endswith(".yml") else workflow + ".yml"
        return _fetch_svg_title(
            f"https://github.com/{slug}/actions/workflows/{wf}/badge.svg"
        )

    titles: dict[str, str | None] = {}
    for wf in _DEFAULT_WORKFLOWS:
        title = _fetch_svg_title(
            f"https://github.com/{slug}/actions/workflows/{wf}/badge.svg"
        )
        titles[wf] = title
        if title and "no status" not in title:
            return title

    return titles.get(_DEFAULT_WORKFLOWS[0])


def fetch_badges(
    repos: dict[str, str | None],
    workers: int = 8,
) -> dict[str, str]:
    """Fetch badge titles for all repos in parallel.

    *repos* maps slug → workflow override (or None for default discovery).
    Returns slug → title string for repos that responded successfully.
    """
    results: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures: list[tuple[str, Future[str | None]]] = [
            (slug, pool.submit(fetch_badge_title, slug, workflow))
            for slug, workflow in repos.items()
        ]
        for slug, future in futures:
            title = future.result()
            if title is not None:
                results[slug] = title

    return results


def write_badges_json(badges: dict[str, str], path: Path) -> None:
    """Write badges dict to a JSON file."""
    data = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repos": badges,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
