"""Subprocess helpers for running Maven and other commands."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)


def run_maven(
    args: list[str],
    *,
    cwd: Path,
    settings: Path | None = None,
    java_home: Path | None = None,
    extra_properties: dict[str, str] | None = None,
    log_path: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Run a Maven command with optional settings and Java home.

    Args:
        args: Maven arguments (e.g., ["clean", "test"]).
        cwd: Working directory (the component source root).
        settings: Path to Maven settings.xml (version-pins).
        java_home: Path to JAVA_HOME for this build.
        extra_properties: Additional -D properties to pass.
        log_path: If provided, write stdout+stderr to this file.
        timeout: Timeout in seconds.

    Returns:
        CompletedProcess with stdout/stderr.
    """
    cmd = ["mvn"]

    if settings:
        cmd.extend(["-s", str(settings)])

    cmd.extend(["-Denforcer.skip"])

    if extra_properties:
        for key, value in extra_properties.items():
            cmd.append(f"-D{key}={value}")

    cmd.extend(args)

    env = None
    if java_home:
        import os

        env = os.environ.copy()
        env["JAVA_HOME"] = str(java_home)
        # Prepend Java bin to PATH
        env["PATH"] = f"{java_home / 'bin'}:{env.get('PATH', '')}"

    _log.info("Running: %s (in %s)", " ".join(cmd), cwd)

    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )

    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w") as f:
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"Working directory: {cwd}\n")
            f.write(f"Exit code: {result.returncode}\n")
            f.write("\n=== STDOUT ===\n")
            f.write(result.stdout)
            f.write("\n=== STDERR ===\n")
            f.write(result.stderr)

    return result
