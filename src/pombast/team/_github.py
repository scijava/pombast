"""Fetch open PR and issue counts from GitHub per repository."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

_log = logging.getLogger(__name__)
_SEARCH_BASE = "https://api.github.com/search/issues"
_DELAY = 7
_MAX_PAGES = 200


@dataclass
class RepoStats:
    prs: int = 0  # open non-draft PRs  (→ reviewer role)
    issues: int = 0  # open issues, not labeled "question"  (→ support role)
    bugs: int = 0  # open issues labeled "bug"  (→ debugger role)
    enhancements: int = 0  # open issues labeled "enhancement", not milestone "unscheduled"  (→ developer role)


def _slug_from(item: dict) -> str:
    return item.get("repository_url", "").removeprefix("https://api.github.com/repos/")


def _search_url(query: str) -> str:
    return f"{_SEARCH_BASE}?q={query}&sort=created&order=asc&per_page=100"


def _paginate(query: str, headers: dict) -> list[dict]:
    items: list[dict] = []
    url = _search_url(query)
    for _ in range(_MAX_PAGES):
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("items", []))
        next_url = resp.links.get("next", {}).get("url")
        if not next_url:
            if data.get("total_count", 0) > 1000 and data.get("items"):
                # Work around GitHub's 1000-result search cap.
                last_created = data["items"][-1]["created_at"]
                next_url = _search_url(f"{query}+created:>{last_created}")
            else:
                break
        url = next_url
        time.sleep(_DELAY)
    return items


def fetch_repo_stats(orgs: set[str], token: str | None = None) -> dict[str, RepoStats]:
    """Return a dict mapping GitHub repo slug → RepoStats for the given orgs."""
    headers: dict[str, str] = {"User-Agent": "pombast"}
    if token:
        headers["Authorization"] = f"token {token}"

    stats: dict[str, RepoStats] = {}

    def _ensure(slug: str) -> RepoStats:
        if slug not in stats:
            stats[slug] = RepoStats()
        return stats[slug]

    for org in sorted(orgs):
        _log.info("Fetching open PRs for org: %s", org)
        for pr in _paginate(f"org:{org}+is:open+is:pr+is:unmerged+-is:draft", headers):
            _ensure(_slug_from(pr)).prs += 1

        _log.info("Fetching open issues for org: %s", org)
        for issue in _paginate(f"org:{org}+is:open+is:issue", headers):
            slug = _slug_from(issue)
            labels = {lbl["name"] for lbl in issue.get("labels", [])}
            milestone = (issue.get("milestone") or {}).get("title", "").lower()

            if "question" not in labels:
                _ensure(slug).issues += 1
            if "bug" in labels:
                _ensure(slug).bugs += 1
            if "enhancement" in labels and milestone != "unscheduled":
                _ensure(slug).enhancements += 1

    return stats
