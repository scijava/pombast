"""Detect the minimum Java version needed to build and test a component."""

from __future__ import annotations

import logging
from pathlib import Path

from jgo.env._bytecode import detect_jar_java_version
from jgo.maven import MavenContext, Model

from bombast.core._component import Component

_log = logging.getLogger(__name__)


def detect_build_java_version(
    component: Component,
    ctx: MavenContext,
    bom_dep_mgmt: dict | None = None,
) -> int | None:
    """Detect the minimum Java version needed to build and test a component.

    Unlike jgo's runtime analysis which only considers compile+runtime scope,
    this considers ALL dependency scopes including test, because bombast needs
    to compile and run tests. A test dependency like mockito-core may require
    a higher Java version than the component itself.

    Args:
        component: The component to analyze.
        ctx: Maven context for fetching POMs and JARs.
        bom_dep_mgmt: The BOM's dependency management dict, used as
            root_dep_mgmt so that BOM-pinned versions (e.g., mockito 5.x)
            take precedence over the component's own dependency management.

    Returns:
        Minimum Java version required (e.g., 8, 11, 17), or None if
        detection fails.
    """
    try:
        pom = ctx.project(component.group, component.name).at_version(
            component.version
        ).pom()
        model = Model(pom, ctx, root_dep_mgmt=bom_dep_mgmt, lenient=True)
    except Exception:
        _log.warning(
            "%s: failed to build model for Java version detection",
            component.coordinate,
        )
        return None

    max_java_version: int | None = None

    # Check all dependencies including test scope.
    for (_g, _a, _c, _t), dep in model.deps.items():
        try:
            jar_path = dep.artifact.resolve()
        except Exception:
            _log.debug(
                "%s: could not resolve JAR for %s:%s:%s",
                component.coordinate,
                dep.groupId,
                dep.artifactId,
                dep.version,
            )
            continue

        if jar_path is None or not jar_path.exists():
            continue

        java_version = detect_jar_java_version(jar_path, round_to_lts_version=False)
        if java_version is not None:
            if max_java_version is None or java_version > max_java_version:
                _log.debug(
                    "%s: %s:%s:%s requires Java %d",
                    component.coordinate,
                    dep.groupId,
                    dep.artifactId,
                    dep.version,
                    java_version,
                )
                max_java_version = java_version

    # Also check the component's own JAR.
    try:
        own_jar = ctx.project(component.group, component.name).at_version(
            component.version
        ).artifact().resolve()
        if own_jar and own_jar.exists():
            own_version = detect_jar_java_version(
                own_jar, round_to_lts_version=False
            )
            if own_version is not None:
                if max_java_version is None or own_version > max_java_version:
                    max_java_version = own_version
    except Exception:
        pass

    if max_java_version is not None:
        # Round up to LTS for practical JDK selection.
        max_java_version = _round_to_lts(max_java_version)
        _log.info(
            "%s: detected build Java version: %d",
            component.coordinate,
            max_java_version,
        )

    return max_java_version


def _round_to_lts(version: int) -> int:
    """Round a Java version up to the nearest LTS version."""
    lts_versions = [8, 11, 17, 21, 25]
    for lts in lts_versions:
        if version <= lts:
            return lts
    return version
