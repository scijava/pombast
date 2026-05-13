"""SCM URL and tag extraction from Maven POMs."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING

from bombast.util._git import ls_remote_tags

if TYPE_CHECKING:
    from jgo.maven import MavenContext

    from bombast.core._component import Component

_log = logging.getLogger(__name__)


def resolve_scm(
    component: Component,
    ctx: MavenContext,
) -> Component:
    """Resolve SCM URL and tag for a component from its POM metadata.

    Returns a new Component with scm_url and scm_tag populated.
    If SCM info cannot be determined, the original component is returned.

    Args:
        component: The component to resolve SCM info for.
        ctx: Maven context for fetching POMs.
    """
    try:
        pom = (
            ctx.project(component.group, component.name)
            .at_version(component.version)
            .pom()
        )
    except Exception:
        _log.warning("%s: failed to fetch POM", component.coordinate)
        return component

    scm_url = _extract_scm_url(pom)
    scm_tag = _extract_scm_tag(pom)

    # If the tag is missing or "HEAD", try to guess it.
    if scm_url and (not scm_tag or scm_tag == "HEAD"):
        _log.info("%s: improper scm tag; scanning remote tags", component.coordinate)
        scm_tag = _guess_tag(scm_url, component.name, component.version)

    return replace(component, scm_url=scm_url, scm_tag=scm_tag)


def _extract_scm_url(pom) -> str | None:
    """Extract and normalize the SCM connection URL from a POM.

    Strips the 'scm:git:' prefix and converts git:// GitHub URLs to https://.
    Falls back to parent POMs via jgo's POM.value() which searches parents.
    """
    connection = pom.value("scm/connection")
    if not connection:
        # Try the generic SCM URL as fallback.
        connection = pom.scmURL
    if not connection:
        return None

    # Strip scm:git: prefix (standard Maven SCM format).
    url = re.sub(r"^scm:git:", "", connection)

    # Convert git:// GitHub URLs to https://.
    url = re.sub(r"^git:(//github\.com/)", r"https:\1", url)

    return url


def _extract_scm_tag(pom) -> str | None:
    """Extract the SCM tag from a POM.

    Returns None if the tag is not set or is "HEAD" (Maven default).
    """
    tag = pom.value("scm/tag")
    if not tag or tag == "HEAD":
        return None
    return tag


def _guess_tag(scm_url: str, artifact_id: str, version: str) -> str | None:
    """Guess the SCM tag for a component by scanning remote tags.

    Tries the following naming conventions in order:
    1. artifactId-version (e.g., "scijava-common-2.99.0")
    2. version (e.g., "2.99.0")
    3. vVersion (e.g., "v2.99.0")

    Args:
        scm_url: The remote repository URL.
        artifact_id: The artifact ID.
        version: The version string.

    Returns:
        The matched tag name, or None if no match found.
    """
    all_tags = ls_remote_tags(scm_url)
    if not all_tags:
        _log.warning("No tags found at %s", scm_url)
        return None

    tag_set = set(all_tags)
    candidates = [
        f"{artifact_id}-{version}",
        version,
        f"v{version}",
    ]

    for candidate in candidates:
        if candidate in tag_set:
            _log.info("Inferred tag: %s", candidate)
            return candidate

    _log.warning(
        "Could not infer tag for %s:%s from %d remote tags",
        artifact_id,
        version,
        len(all_tags),
    )
    return None
