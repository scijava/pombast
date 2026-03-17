"""Load managed dependencies from a Maven BOM."""

from __future__ import annotations

import logging
from pathlib import Path

from jgo.maven import MavenContext, Model

from bombast.core._component import Component

_log = logging.getLogger(__name__)


def load_bom(
    bom: str,
    *,
    repositories: dict[str, str] | None = None,
) -> list[Component]:
    """Load all managed dependencies from a Maven BOM.

    Args:
        bom: A G:A:V coordinate (e.g., "org.scijava:pom-scijava:37.0.0")
            or a path to a local directory containing a pom.xml.
        repositories: Additional remote Maven repositories (name → URL).

    Returns:
        List of Component objects representing each managed dependency.
    """
    remote_repos = {"central": "https://repo1.maven.org/maven2"}
    if repositories:
        remote_repos.update(repositories)

    ctx = MavenContext(remote_repos=remote_repos)

    bom_path = Path(bom)
    if bom_path.is_dir() or bom_path.joinpath("pom.xml").exists():
        pom = _load_local_bom(bom_path, ctx)
    elif ":" in bom:
        pom = _load_remote_bom(bom, ctx)
    else:
        raise FileNotFoundError(f"Not a directory and not a G:A:V coordinate: {bom}")

    model = Model(pom, ctx, lenient=True)
    _log.info(
        "Loaded BOM with %d managed dependencies", len(model.dep_mgmt)
    )

    components = []
    seen: set[str] = set()
    for (group_id, artifact_id, classifier, type_pkg), dep in sorted(
        model.dep_mgmt.items()
    ):
        # Skip BOM imports (scope=import, type=pom) — these are not
        # buildable components, they are just dependency management containers.
        if dep.scope == "import" and dep.type == "pom":
            continue

        # Skip non-jar artifacts (e.g., pom-only, test-jar, etc.)
        # unless they have the default packaging.
        if type_pkg not in ("jar", "bundle", "maven-plugin"):
            continue

        # Skip classified artifacts (e.g., sources, javadoc, natives).
        # We only want the primary artifact for each G:A.
        if classifier:
            continue

        version = dep.version
        if not version:
            _log.warning("Skipping %s:%s — no version", group_id, artifact_id)
            continue

        # Deduplicate by G:A — keep the first entry seen.
        ga = f"{group_id}:{artifact_id}"
        if ga in seen:
            continue
        seen.add(ga)

        components.append(
            Component(
                group=group_id,
                name=artifact_id,
                version=version,
            )
        )

    _log.info("Extracted %d components from BOM", len(components))
    return components


def _load_local_bom(bom_dir: Path, ctx: MavenContext):
    """Load a BOM POM from a local directory."""
    from jgo.maven import POM

    pom_path = bom_dir / "pom.xml"
    if not pom_path.exists():
        raise FileNotFoundError(f"No pom.xml found in {bom_dir}")
    return POM(pom_path)


def _load_remote_bom(bom: str, ctx: MavenContext):
    """Load a BOM POM from Maven coordinates."""
    parts = bom.split(":")
    if len(parts) < 3:
        raise ValueError(
            f"BOM must be a G:A:V coordinate (got {bom!r}). "
            "Use a directory path for local BOMs."
        )
    group_id, artifact_id, version = parts[0], parts[1], parts[2]

    component = ctx.project(group_id, artifact_id).at_version(version)
    return component.pom()
