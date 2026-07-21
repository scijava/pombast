"""Resolve a component's actual dependency versions (and target Java) via jgo.

Crosslinking must point at the versions a component *actually* depends on — as
Maven would resolve them — not the versions the BOM happens to manage. jgo is the
single source of resolution truth here, exactly as in the smelt Java-version
analysis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pombast.core._component import Component

if TYPE_CHECKING:
    from jgo.maven import MavenContext

_log = logging.getLogger(__name__)

# Effective POM properties that declare a component's target Java version, in
# preference order. Read straight from the resolved model (no artifact download),
# these reflect the true JVM the component targets even when the javadoc's baked
# JDK-link prefix (e.g. a stale "/Java8/") disagrees.
_JAVA_VERSION_PROPS = (
    "maven.compiler.release",
    "maven.compiler.target",
    "scijava.jvm.version",
    "maven.compiler.source",
)


@dataclass
class Closure:
    """A component's resolved dependency closure plus its target Java version."""

    deps: list[Component] = field(default_factory=list)
    java_version: int | None = None


def resolve_closure(ctx: MavenContext, comp: Component) -> Closure:
    """Resolve ``comp``'s dependency closure and target Java version.

    Transitive (nearest-wins) primary artifacts only: classified artifacts
    (sources/javadoc/natives) and test-scope dependencies are dropped, since
    neither appears in a component's public javadoc signatures. Order is jgo's
    breadth-first nearest-first, which sets the first-wins precedence used when
    building the class index. Deduplicated by G:A. On failure returns an empty
    closure.
    """
    from jgo.maven import Model

    try:
        pom = ctx.project(comp.group, comp.name).at_version(comp.version).pom()
        model = Model(pom, ctx, lenient=True)
        deps, _tree = model.dependencies()
    except Exception as e:
        _log.warning("Failed to resolve dependencies for %s: %s", comp.coordinate, e)
        return Closure()

    result: list[Component] = []
    seen: set[str] = set()
    for d in deps:
        if d.classifier:
            continue
        if d.scope == "test":
            continue
        ga = f"{d.groupId}:{d.artifactId}"
        if ga in seen:
            continue
        seen.add(ga)
        result.append(Component(group=d.groupId, name=d.artifactId, version=d.version))

    return Closure(deps=result, java_version=_java_version(model.props))


def _java_version(props: dict[str, str]) -> int | None:
    """Extract the target major Java version from resolved POM properties."""
    for key in _JAVA_VERSION_PROPS:
        raw = props.get(key)
        if raw:
            parsed = _parse_java_version(raw)
            if parsed is not None:
                return parsed
    return None


def _parse_java_version(raw: str) -> int | None:
    """Parse a Java version token: ``"1.8"`` → 8, ``"8"`` → 8, ``"21"`` → 21."""
    token = raw.strip()
    if token.startswith("1."):
        token = token[2:]
    try:
        return int(token.split(".")[0])
    except ValueError:
        return None
