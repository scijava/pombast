"""Classify component version bumps by their bytecode-floor blast radius.

A bump's *blast radius* is how far raising a component's bytecode floor would
propagate through the BOM's own dependency graph:

- **flat** — the candidate does not raise the component's effective floor;
  safe for everyone.
- **local** — it raises only this component's own floor; safe within the BOM,
  but visible to external consumers targeting a lower JVM.
- **cascading** — it raises this component *and* at least one other BOM
  component that (transitively) depends on it.
- **excluded** — its effective floor exceeds the runtime cap the BOM commits to;
  it would require a newer JVM than the BOM targets, so it is ruled out.

The consumer graph and per-component floors come from a prior smelt run
(``smelt.json``); the only genuinely new input is each candidate version's own
bytecode, which the caller supplies (it requires scanning the published JAR).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_LTS_VERSIONS = (8, 11, 17, 21, 25)

# Ordered by increasing severity, so the worst class among a set of candidates
# (the "frontier") is the one with the highest value here.
_SEVERITY = {"flat": 0, "local": 1, "cascading": 2, "excluded": 3}


def round_up_to_lts(version: int) -> int:
    """Round a bytecode/Java version up to the nearest LTS release."""
    for lts in _LTS_VERSIONS:
        if version <= lts:
            return lts
    return version


@dataclass
class LadderStep:
    """One candidate version's classification, for the per-Java-level tooltip."""

    version: str
    floor: int | None  # effective bytecode floor of this candidate (raw)
    java_level: int | None  # floor rounded up to the nearest LTS
    klass: str  # flat | local | cascading | excluded | unknown
    lifted: list[str] = field(default_factory=list)  # consumer G:As (cascading)


@dataclass
class BumpClassification:
    """The result of classifying all accepted bumps for one component."""

    recommended: str | None  # newest flat bump above current, else None
    frontier_class: str | None  # worst class present among candidates, else None
    ladder: list[LadderStep] = field(default_factory=list)


def build_consumer_index(
    closures: Mapping[str, Sequence[str]],
) -> dict[str, set[str]]:
    """Map each managed G:A to the set of components whose closure contains it.

    Each closure entry is a ``g:a:c:t:v`` string; the consumer relationship is
    keyed on G:A only. Because closures are transitive, this index captures
    transitive consumers directly — a component appears against every G:A
    anywhere in its resolved closure.
    """
    index: dict[str, set[str]] = {}
    for ga, closure in closures.items():
        for entry in closure:
            parts = entry.split(":")
            if len(parts) < 2:
                continue
            dep_ga = f"{parts[0]}:{parts[1]}"
            index.setdefault(dep_ga, set()).add(ga)
    return index


def candidate_floor(
    own_new: int | None,
    current_own: int | None,
    current_effective: int | None,
) -> int | None:
    """Approximate a candidate version's effective bytecode floor.

    The exact floor would require resolving the candidate's full dependency
    closure. This approximates it from the candidate's own bytecode plus the
    *current* version's dependency-driven contribution, assuming the candidate
    pulls in no heavier dependencies than the current version does. When the
    current effective floor was itself dependency-driven (higher than the
    component's own bytecode), that contribution is carried forward.
    """
    dep_contrib = (
        current_effective
        if current_effective is not None
        and (current_own is None or current_effective > current_own)
        else None
    )
    vals = [v for v in (own_new, dep_contrib) if v is not None]
    return max(vals) if vals else None


class BumpClassifier:
    """Classifies version bumps against a BOM's bytecode floors and consumer graph."""

    def __init__(
        self,
        *,
        floors: Mapping[str, int],
        closures: Mapping[str, Sequence[str]],
        runtime_cap: int,
    ) -> None:
        """Build a classifier from per-component floors and closures.

        Args:
            floors: G:A → current effective bytecode floor (from smelt.json).
            closures: G:A → resolved dependency closure (``g:a:c:t:v`` entries),
                used to build the consumer graph.
            runtime_cap: Highest JVM the BOM commits to; candidates above it are
                classified ``excluded``.
        """
        self._floors = dict(floors)
        self._consumers = build_consumer_index(closures)
        self._cap = runtime_cap

    def _classify_floor(
        self, ga: str, cand_floor: int | None, current_floor: int | None
    ) -> tuple[str, list[str]]:
        if cand_floor is None or current_floor is None:
            return "unknown", []
        if cand_floor <= current_floor:
            return "flat", []
        if cand_floor > self._cap:
            return "excluded", []
        lifted = sorted(
            k
            for k in self._consumers.get(ga, ())
            if k != ga
            and self._floors.get(k) is not None
            and self._floors[k] < cand_floor
        )
        if lifted:
            return "cascading", lifted
        return "local", []

    def classify(
        self, ga: str, candidates: Iterable[tuple[str, int | None]]
    ) -> BumpClassification:
        """Classify a component's candidate bumps.

        Args:
            ga: The component's G:A.
            candidates: ``(version, candidate_floor)`` pairs, newest first.

        Returns:
            A BumpClassification with the recommended (newest flat) version, the
            frontier (worst) class present, and a per-candidate ladder.
        """
        current_floor = self._floors.get(ga)
        ladder: list[LadderStep] = []
        recommended: str | None = None
        frontier: str | None = None
        for version, cand_floor in candidates:
            klass, lifted = self._classify_floor(ga, cand_floor, current_floor)
            ladder.append(
                LadderStep(
                    version=version,
                    floor=cand_floor,
                    java_level=round_up_to_lts(cand_floor)
                    if cand_floor is not None
                    else None,
                    klass=klass,
                    lifted=lifted,
                )
            )
            # Newest-first: the first flat candidate seen is the newest flat one.
            if klass == "flat" and recommended is None:
                recommended = version
            if klass in _SEVERITY and (
                frontier is None or _SEVERITY[klass] > _SEVERITY[frontier]
            ):
                frontier = klass
        return BumpClassification(
            recommended=recommended, frontier_class=frontier, ladder=ladder
        )
