"""Detect the minimum Java version needed to build and test a component, and
render the resolved dependency tree used to reach that decision."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from jgo.cli.rich import format_dependency_tree
from jgo.env import jar_java_version
from jgo.maven import POM, MavenContext, Model
from rich.console import Console

if TYPE_CHECKING:
    from pathlib import Path

    from jgo.maven import DependencyNode

    from pombast.core._component import Component

_log = logging.getLogger(__name__)

_LTS_VERSIONS = (8, 11, 17, 21, 25)


@dataclass
class JavaVersionAnalysis:
    """Outcome of analyzing a component's dependency closure for its Java version.

    Attributes:
        java_version: Minimum JDK to use, rounded up to the nearest LTS. None if
            detection failed.
        raw_max: Highest bytecode version actually observed across the component's
            own JAR *and* its dependency closure, before LTS rounding. This is the
            component's *effective* bytecode floor — the lowest JVM that can run it
            together with its BOM-pinned dependencies.
        own_bytecode: Bytecode version of the component's own JAR alone, before LTS
            rounding. May be lower than ``raw_max`` when a dependency forces a higher
            floor. None if the component's JAR could not be scanned.
        drivers: Coordinates of the dependencies whose bytecode is at ``raw_max``
            (i.e. the artifacts that forced the choice).
        tree: The resolved (BOM-pinned) dependency tree, for rendering to a log.
        closure: The fully resolved dependency set as ``g:a:c:t:v`` (GACT plus
            version) entries — the per-component success-cache key. Excludes the
            component's own artifact; empty if resolution failed.
    """

    java_version: int | None = None
    raw_max: int | None = None
    own_bytecode: int | None = None
    drivers: list[str] = field(default_factory=list)
    tree: DependencyNode | None = None
    closure: list[str] = field(default_factory=list)


def analyze_build_java(
    component: Component,
    ctx: MavenContext,
    pom_path: Path,
) -> JavaVersionAnalysis:
    """Resolve a component's full transitive closure and detect its build Java version.

    Unlike jgo's runtime analysis (which only considers compile+runtime scope), this
    walks the entire resolved closure *including* direct test-scope dependencies,
    because pombast must compile and run the test suite. Crucially it inspects
    transitive dependencies too: the Java requirement frequently comes from an
    indirectly pulled artifact (e.g. SciFIO compiled for Java 11) rather than anything
    the component declares directly. Inspecting only the directly declared
    dependencies would silently miss that and select too low a JDK.

    Resolution is driven from the component's *rewritten* POM on disk — the one
    pombast has already pinned to the BOM under test — so jgo resolves exactly the
    same versions Maven will build (e.g. SciFIO 0.49.0, which is Java 11). This keeps
    jgo as the single source of resolution truth; pombast does not second-guess
    dependency management in Python.

    Args:
        component: The component being analyzed (for the own-JAR check and labels).
        ctx: Maven context for resolving JARs.
        pom_path: Path to the rewritten, BOM-pinned ``pom.xml`` in the clone.

    Returns:
        A JavaVersionAnalysis. On failure its fields are left at their defaults
        (``java_version`` is None, ``tree`` is None).
    """
    analysis = JavaVersionAnalysis()
    try:
        model = Model(POM(pom_path), ctx, lenient=True)
        deps, analysis.tree = model.dependencies()
    except Exception:
        _log.warning(
            "%s: failed to resolve dependencies for Java version detection",
            component.coordinate,
        )
        return analysis

    # The fully resolved dependency set is also the per-component success-cache
    # key: record each entry with full GACT precision so it can be revalidated
    # against the GACT-keyed BOM dependency management on a later run.
    analysis.closure = sorted(
        f"{d.groupId}:{d.artifactId}:{d.classifier}:{d.type}:{d.version}" for d in deps
    )

    # Every artifact in the resolved closure, plus the component's own JAR.
    artifacts = [(f"{d.groupId}:{d.artifactId}:{d.version}", d.artifact) for d in deps]
    try:
        artifacts.append(
            (
                component.coordinate,
                ctx.project(component.group, component.name)
                .at_version(component.version)
                .artifact(),
            )
        )
    except Exception:
        pass

    max_version: int | None = None
    own_bytecode: int | None = None
    drivers: list[str] = []
    for coord, artifact in artifacts:
        # jgo resolves the JAR and caches the bytecode scan per artifact (in-process
        # plus on disk), so repeated lookups across components stay cheap.
        jver = jar_java_version(artifact, round_to_lts_version=False)
        if jver is None:
            continue
        if coord == component.coordinate:
            own_bytecode = jver
        if max_version is None or jver > max_version:
            max_version = jver
            drivers = [coord]
        elif jver == max_version:
            drivers.append(coord)

    analysis.own_bytecode = own_bytecode
    if max_version is not None:
        analysis.raw_max = max_version
        analysis.drivers = drivers
        analysis.java_version = _round_to_lts(max_version)
        _log.info(
            "%s: detected build Java version: %d",
            component.coordinate,
            analysis.java_version,
        )

    return analysis


def write_dependency_tree_log(
    analysis: JavaVersionAnalysis,
    component: Component,
    log_path: Path,
) -> None:
    """Write the resolved dependency tree plus the Java-version rationale to a log.

    This is the per-component analog of the ``dependency-tree.log`` that mega-melt
    writes, rendered from the same resolution pombast used to pick the JDK (so it
    can't disagree with that choice). The summary header calls out which dependency
    forced the Java version, making failures like a transitively-pulled Java 11
    artifact on a Java 8 build self-explanatory.

    Best-effort: any failure to render or write is logged at debug level and
    swallowed, since a diagnostic log must never fail the build.
    """
    if analysis.tree is None:
        return
    try:
        tree = format_dependency_tree(analysis.tree, no_wrap=True)
        buf = io.StringIO()
        # Plain text (no ANSI) so the log greps cleanly.
        Console(file=buf, color_system=None, width=200).print(tree)

        header = [
            f"Dependency tree for {component.coordinate}",
            "Versions resolved against the BOM under test (jgo resolution).",
            "",
        ]
        if analysis.java_version is None:
            header.append("Detected build Java version: unknown")
        else:
            rounded = (
                f" (rounded up from Java {analysis.raw_max})"
                if analysis.raw_max and analysis.raw_max != analysis.java_version
                else ""
            )
            header.append(
                f"Detected build Java version: {analysis.java_version}{rounded}"
            )
            if analysis.raw_max and analysis.raw_max > 8 and analysis.drivers:
                header.append(f"Required by (Java {analysis.raw_max} bytecode):")
                header.extend(f"  - {coord}" for coord in analysis.drivers)
            else:
                header.append("No dependency requires newer than Java 8.")
        header.append("")

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(header) + "\n" + buf.getvalue())
    except Exception as e:
        _log.debug(
            "%s: could not write dependency tree log: %s", component.coordinate, e
        )


def _round_to_lts(version: int) -> int:
    """Round a Java version up to the nearest LTS version."""
    for lts in _LTS_VERSIONS:
        if version <= lts:
            return lts
    return version
