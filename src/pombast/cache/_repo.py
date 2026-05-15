"""Bare git repository cache management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pombast.util._git import bare_clone, default_branch, fetch_tags, has_ref

if TYPE_CHECKING:
    from pombast.core._component import Component

_log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "pombast" / "repos"


class RepoCache:
    """Manages a cache of bare git repositories for source resolution.

    Repositories are stored at {cache_dir}/{groupId}/{artifactId} as
    bare clones. They are created on first use and updated lazily
    (only when a needed tag is not found).
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR

    def repo_path(self, component: Component) -> Path:
        """Return the cache path for a component's bare repository."""
        return self.cache_dir / component.group / component.name

    def ensure_repo(self, component: Component, scm_url: str) -> Path:
        """Ensure a bare repository exists in the cache, cloning if needed.

        Args:
            component: The component whose source is needed.
            scm_url: The remote repository URL to clone from.

        Returns:
            Path to the bare repository in the cache.
        """
        repo = self.repo_path(component)
        if not repo.exists():
            _log.info(
                "%s: cached repo not found; cloning from %s",
                component.coordinate,
                scm_url,
            )
            bare_clone(scm_url, repo)
        return repo

    def ensure_ref(self, component: Component, scm_url: str, ref: str) -> Path:
        """Ensure the cache has a bare repo containing the given ref.

        If the ref is not found, fetches tags from the remote.

        Args:
            component: The component.
            scm_url: Remote repository URL.
            ref: Tag or branch name to ensure is available.

        Returns:
            Path to the bare repository in the cache.
        """
        repo = self.ensure_repo(component, scm_url)

        if not has_ref(repo, ref):
            _log.info(
                "%s: ref '%s' not found locally; fetching from remote",
                component.coordinate,
                ref,
            )
            fetch_tags(repo)

        return repo

    def get_default_branch(self, component: Component) -> str:
        """Get the default branch name for a cached repository."""
        repo = self.repo_path(component)
        return default_branch(repo)
