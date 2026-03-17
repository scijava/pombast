"""Git operations for cloning and caching repositories."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)


def bare_clone(url: str, dest: Path) -> None:
    """Clone a repository as a bare clone.

    Args:
        url: Remote repository URL.
        dest: Destination path for the bare repository.
    """
    _log.info("Cloning bare repository: %s -> %s", url, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--bare", url, str(dest)])


def fetch_tags(repo: Path) -> None:
    """Fetch tags from the remote in a bare repository.

    Args:
        repo: Path to a bare git repository.
    """
    _log.debug("Fetching tags in %s", repo)
    _run(["git", "fetch", "--tags"], cwd=repo)


def shallow_clone(
    repo: Path,
    branch: str,
    dest: Path,
) -> None:
    """Shallow clone from a (bare) repository at a specific branch/tag.

    Args:
        repo: Path to the source repository (bare or regular).
        branch: Branch or tag name to check out.
        dest: Destination path for the clone.
    """
    _log.info("Shallow cloning %s@%s -> %s", repo, branch, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "git", "clone",
        f"file://{repo}",
        "--branch", branch,
        "--depth", "1",
        str(dest),
    ])


def has_ref(repo: Path, ref: str) -> bool:
    """Check whether a bare repository contains a given tag or branch ref.

    Args:
        repo: Path to a bare git repository.
        ref: Tag or branch name to look for.

    Returns:
        True if the ref exists in the repository.
    """
    result = subprocess.run(
        ["git", "ls-remote", f"file://{repo}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False

    for line in result.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            remote_ref = parts[1]
            if remote_ref == f"refs/tags/{ref}" or remote_ref == f"refs/heads/{ref}":
                return True
    return False


def ls_remote_tags(url: str) -> list[str]:
    """List all tags on a remote repository.

    Args:
        url: Remote repository URL.

    Returns:
        List of tag names (without refs/tags/ prefix).
    """
    result = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _log.warning("Failed to list remote tags for %s", url)
        return []

    tags = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            ref = parts[1]
            if ref.startswith("refs/tags/"):
                tag = ref[len("refs/tags/"):]
                # Skip ^{} dereferenced tag entries.
                if not tag.endswith("^{}"):
                    tags.append(tag)
    return tags


def default_branch(repo: Path) -> str:
    """Get the default branch name from a bare repository's HEAD.

    Args:
        repo: Path to a bare git repository.

    Returns:
        The branch name (e.g., "main" or "master").
    """
    head_file = repo / "HEAD"
    if head_file.exists():
        content = head_file.read_text().strip()
        # HEAD typically contains "ref: refs/heads/main"
        if content.startswith("ref: refs/heads/"):
            return content[len("ref: refs/heads/"):]
    return "main"


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a git command, raising on failure."""
    _log.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        _log.error("git command failed: %s\n%s", " ".join(cmd), result.stderr)
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result
