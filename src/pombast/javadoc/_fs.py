"""Filesystem helpers that never modify an existing file's inode in place.

The javadoc build tree is published by hard-linking it into the served tree, so
any file the two trees share is the *same* inode. Writing such a file in place
(``Path.write_text``, ``ZipFile.extractall`` over an existing dir) would leak a
half-written edit straight into production. Instead, every write goes to a fresh
temporary file that atomically replaces the old path, leaving the served link
pointing at the untouched original until the next publish.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@contextmanager
def atomic_writer(
    path: Path, *, encoding: str = "utf-8", errors: str = "strict"
) -> Iterator[TextIO]:
    """Open a temp file that atomically replaces ``path`` (new inode) on success.

    On error the temp file is discarded and ``path`` is left untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, errors=errors, newline="") as f:
            yield f
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def atomic_write_text(
    path: Path, text: str, *, encoding: str = "utf-8", errors: str = "strict"
) -> None:
    """Write ``text`` to ``path`` via a temp file + rename (new inode)."""
    with atomic_writer(path, encoding=encoding, errors=errors) as f:
        f.write(text)


def swap_dir(staged: Path, dest: Path) -> None:
    """Move a fully-populated ``staged`` dir into place at ``dest``.

    Any existing ``dest`` is renamed aside first and then deleted, so ``dest`` is
    never observed half-populated and none of its old inodes are modified.
    """
    old = None
    if dest.exists():
        old = dest.with_name(f".{dest.name}.old")
        if old.exists():
            shutil.rmtree(old)
        os.replace(dest, old)
    os.replace(staged, dest)
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)
