"""Aggregate GitHub issue/PR data into per-repo stats."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from monoqueue.github import DEFAULT_CACHE_DIR, DEFAULT_MAX_AGE, fetch_items

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class RepoItem:
    url: str
    title: str
    number: int
    repo: str  # e.g. "imagej/imagej-common"


@dataclass
class RepoStats:
    prs: list[RepoItem] = field(default_factory=list)
    issues: list[RepoItem] = field(default_factory=list)
    bugs: list[RepoItem] = field(default_factory=list)
    enhancements: list[RepoItem] = field(default_factory=list)


def fetch_repo_stats(
    orgs: set[str],
    token: str | None = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    max_age: int = DEFAULT_MAX_AGE,
    refresh: bool = False,
    progress=None,
) -> dict[str, RepoStats]:
    """Return a dict mapping GitHub repo slug → RepoStats for the given orgs."""
    items = fetch_items(
        orgs=orgs,
        token=token,
        cache_dir=cache_dir,
        max_age=max_age,
        refresh=refresh,
        progress=progress,
    )
    stats: dict[str, RepoStats] = defaultdict(RepoStats)
    for item in items:
        slug = item["repository_url"].removeprefix("https://api.github.com/repos/")
        labels = {lbl["name"] for lbl in item.get("labels", [])}
        milestone = (item.get("milestone") or {}).get("title", "").lower()
        ri = RepoItem(
            url=item.get("html_url", ""),
            title=item.get("title", ""),
            number=item.get("number", 0),
            repo=slug,
        )
        if "pull_request" in item:
            if not item.get("draft", False):
                stats[slug].prs.append(ri)
        else:
            if "question" not in labels:
                stats[slug].issues.append(ri)
            if "bug" in labels:
                stats[slug].bugs.append(ri)
            if "enhancement" in labels and milestone != "unscheduled":
                stats[slug].enhancements.append(ri)
    return dict(stats)
