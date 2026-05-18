"""Load managed dependencies from a Maven BOM."""

from __future__ import annotations

import logging
from pathlib import Path

from jgo.maven import MavenContext, Model

from pombast.core._component import Component

_log = logging.getLogger(__name__)


class BomData:
    """Result of loading a Maven BOM."""

    def __init__(
        self,
        components: list[Component],
        dep_mgmt: dict,
        ctx: MavenContext,
        pom_path: Path,
    ):
        self.components = components
        self.dep_mgmt = dep_mgmt
        self.ctx = ctx
        self.pom_path = pom_path


def load_bom(
    bom: str,
    *,
    repositories: dict[str, str] | None = None,
) -> BomData:
    """Load all managed dependencies from a Maven BOM.

    Args:
        bom: A G:A:V coordinate (e.g., "org.scijava:pom-scijava:37.0.0")
            or a path to a local directory containing a pom.xml.
        repositories: Additional remote Maven repositories (name → URL).

    Returns:
        BomData with components, the BOM's dep_mgmt dict, and MavenContext.
    """
    remote_repos = dict(repositories) if repositories else {}
    remote_repos.setdefault("central", "https://repo1.maven.org/maven2")

    ctx = MavenContext(remote_repos=remote_repos)

    bom_path = Path(bom)
    if bom_path.is_dir() or bom_path.joinpath("pom.xml").exists():
        pom = _load_local_bom(bom_path, ctx)
        pom_file = bom_path / "pom.xml"
    elif ":" in bom:
        pom = _load_remote_bom(bom, ctx)
        pom_file = _remote_pom_path(bom, ctx)
    else:
        raise FileNotFoundError(f"Not a directory and not a G:A:V coordinate: {bom}")

    model = Model(pom, ctx, lenient=True)
    _log.info("Loaded BOM with %d managed dependencies", len(model.dep_mgmt))

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
    return BomData(
        components=components, dep_mgmt=model.dep_mgmt, ctx=ctx, pom_path=pom_file
    )


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


def _remote_pom_path(bom: str, ctx: MavenContext) -> Path:
    """Compute the local cache path for a remote BOM's POM file."""
    parts = bom.split(":")
    group_id, artifact_id, version = parts[0], parts[1], parts[2]
    group_path = group_id.replace(".", "/")
    return (
        Path(ctx.repo_cache)
        / group_path
        / artifact_id
        / version
        / f"{artifact_id}-{version}.pom"
    )
