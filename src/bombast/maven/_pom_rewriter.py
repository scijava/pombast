"""Rewrite component POM to hardcode dependency versions from a BOM."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_log = logging.getLogger(__name__)

# Maven POM namespace.
_NS = "http://maven.apache.org/POM/4.0.0"

# Pattern matching http:// URLs, but NOT the POM namespace URI.
_HTTP_URL = re.compile(r"http://(?!maven\.apache\.org/POM/)")


def patch_pom_urls(pom_path: Path) -> bool:
    """Upgrade http:// URLs to https:// in a POM file.

    Modern Maven blocks plain http:// repository URLs.  This replaces
    all http:// occurrences with https://, except the POM namespace URI
    (http://maven.apache.org/POM/4.0.0) which is an XML identifier,
    not a network URL.

    Returns True if any replacements were made.
    """
    text = pom_path.read_text(encoding="UTF-8")
    patched = _HTTP_URL.sub("https://", text)

    if patched != text:
        pom_path.write_text(patched, encoding="UTF-8")
        _log.info("Patched http→https URLs in %s", pom_path.name)
        return True
    return False


def rewrite_pom_versions(
    pom_path: Path,
    dep_mgmt: dict,
) -> int:
    """Rewrite a component's pom.xml to pin dependency versions from a BOM.

    Two-pronged approach:
    1. Inject the full BOM dependency management as the component's
       own <dependencyManagement> block.  The project's own direct
       dependency management takes precedence over what the parent
       POM provides, so this overrides inherited version management.
    2. Hardcode <version> on every <dependency> element whose G:A
       appears in the BOM's dep_mgmt, overriding any property
       references or omitted versions.

    Together these ensure that both transitive resolution and direct
    dependency declarations conform to the BOM being tested.

    Args:
        pom_path: Path to the pom.xml to rewrite.
        dep_mgmt: BOM dependency management dict mapping
            (groupId, artifactId, classifier, type) → Dependency.

    Returns:
        Number of dependency versions rewritten (prong 2 only;
        the dep_mgmt injection is not counted).
    """
    ET.register_namespace("", _NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

    tree = ET.parse(pom_path)
    root = tree.getroot()

    # Prong 1: Inject full dependency management.
    dm_injected = _inject_dependency_management(root, dep_mgmt)

    # Prong 2: Hardcode versions on all <dependency> elements.
    count = _rewrite_dependency_versions(root, dep_mgmt)

    if count > 0 or dm_injected:
        ET.indent(tree, space="\t")
        tree.write(pom_path, xml_declaration=True, encoding="UTF-8")
        _log.info("Rewrote %d dependency version(s) in %s", count, pom_path.name)

    return count


def _inject_dependency_management(root: ET.Element, dep_mgmt: dict) -> bool:
    """Inject the BOM's full dependency management into the POM.

    Replaces or creates the <dependencyManagement><dependencies>
    block with all entries from the BOM.  Because Maven resolves
    the project's own <dependencyManagement> before the parent's,
    this overrides any inherited version management.

    Returns True if any entries were injected.
    """
    if not dep_mgmt:
        return False

    # Find or create <dependencyManagement>.
    dm_elem = root.find(f"{{{_NS}}}dependencyManagement")
    if dm_elem is None:
        dm_elem = ET.SubElement(root, f"{{{_NS}}}dependencyManagement")

    # Find or create <dependencies> inside it.
    deps_elem = dm_elem.find(f"{{{_NS}}}dependencies")
    if deps_elem is None:
        deps_elem = ET.SubElement(dm_elem, f"{{{_NS}}}dependencies")

    # Build a set of G:A:C:T already present so we can update or add.
    existing: dict[tuple, ET.Element] = {}
    for dep in deps_elem.findall(f"{{{_NS}}}dependency"):
        g = dep.find(f"{{{_NS}}}groupId")
        a = dep.find(f"{{{_NS}}}artifactId")
        if g is None or a is None:
            continue
        c_elem = dep.find(f"{{{_NS}}}classifier")
        t_elem = dep.find(f"{{{_NS}}}type")
        c = (c_elem.text or "").strip() if c_elem is not None else ""
        t = (t_elem.text or "").strip() if t_elem is not None else "jar"
        existing[(g.text, a.text, c, t)] = dep

    injected = 0
    for key, bom_dep in sorted(dep_mgmt.items()):
        group_id, artifact_id, classifier, dep_type = key
        version = bom_dep.version
        if not version:
            continue

        if key in existing:
            # Update existing entry's version.
            v_elem = existing[key].find(f"{{{_NS}}}version")
            if v_elem is not None:
                if v_elem.text == version:
                    continue
                v_elem.text = version
            else:
                v_elem = ET.SubElement(existing[key], f"{{{_NS}}}version")
                v_elem.text = version
            injected += 1
        else:
            # Create new entry.
            dep_elem = ET.SubElement(deps_elem, f"{{{_NS}}}dependency")
            g_elem = ET.SubElement(dep_elem, f"{{{_NS}}}groupId")
            g_elem.text = group_id
            a_elem = ET.SubElement(dep_elem, f"{{{_NS}}}artifactId")
            a_elem.text = artifact_id
            v_elem = ET.SubElement(dep_elem, f"{{{_NS}}}version")
            v_elem.text = version
            if dep_type != "jar":
                t_elem = ET.SubElement(dep_elem, f"{{{_NS}}}type")
                t_elem.text = dep_type
            if classifier:
                c_elem = ET.SubElement(dep_elem, f"{{{_NS}}}classifier")
                c_elem.text = classifier
            # Preserve scope from BOM (e.g. import for BOM-type entries).
            scope = getattr(bom_dep, "scope", None)
            if scope and scope != "compile":
                s_elem = ET.SubElement(dep_elem, f"{{{_NS}}}scope")
                s_elem.text = scope
            injected += 1

    if injected > 0:
        _log.info("Injected %d dependency management entries into POM", injected)

    return injected > 0


def _rewrite_dependency_versions(root: ET.Element, dep_mgmt: dict) -> int:
    """Hardcode <version> on all <dependency> elements from the BOM.

    Only rewrites dependencies outside of <dependencyManagement>,
    since that section was already handled by prong 1.
    """
    count = 0

    # Collect dependency elements that live outside <dependencyManagement>.
    # We iterate specific known locations rather than using root.iter(),
    # which would also pick up the deps we just injected in prong 1.
    dep_containers = []

    # Top-level <dependencies>.
    top_deps = root.find(f"{{{_NS}}}dependencies")
    if top_deps is not None:
        dep_containers.append(top_deps)

    # <dependencies> inside <profiles>/<profile>.
    for profile in root.iter(f"{{{_NS}}}profile"):
        profile_deps = profile.find(f"{{{_NS}}}dependencies")
        if profile_deps is not None:
            dep_containers.append(profile_deps)

    for container in dep_containers:
        for dep_elem in container.findall(f"{{{_NS}}}dependency"):
            group_elem = dep_elem.find(f"{{{_NS}}}groupId")
            artifact_elem = dep_elem.find(f"{{{_NS}}}artifactId")
            if group_elem is None or artifact_elem is None:
                continue

            group_id = (group_elem.text or "").strip()
            artifact_id = (artifact_elem.text or "").strip()
            if not group_id or not artifact_id:
                continue

            # Determine classifier and type for lookup.
            classifier_elem = dep_elem.find(f"{{{_NS}}}classifier")
            type_elem = dep_elem.find(f"{{{_NS}}}type")
            classifier = (
                (classifier_elem.text or "").strip()
                if classifier_elem is not None
                else ""
            )
            dep_type = (
                (type_elem.text or "").strip() if type_elem is not None else "jar"
            )

            # Look up in BOM dep_mgmt.
            key = (group_id, artifact_id, classifier, dep_type)
            bom_dep = dep_mgmt.get(key)
            if bom_dep is None and classifier:
                bom_dep = dep_mgmt.get((group_id, artifact_id, "", dep_type))
            if bom_dep is None:
                continue

            bom_version = bom_dep.version
            if not bom_version:
                continue

            # Set or update the <version> element.
            version_elem = dep_elem.find(f"{{{_NS}}}version")
            if version_elem is not None:
                old_version = (version_elem.text or "").strip()
                if old_version == bom_version:
                    continue
                version_elem.text = bom_version
                _log.debug(
                    "  %s:%s version %s → %s",
                    group_id,
                    artifact_id,
                    old_version,
                    bom_version,
                )
            else:
                # Insert <version> after <artifactId>.
                version_elem = ET.Element(f"{{{_NS}}}version")
                version_elem.text = bom_version
                children = list(dep_elem)
                idx = children.index(artifact_elem)
                dep_elem.insert(idx + 1, version_elem)
                _log.debug(
                    "  %s:%s version (added) → %s",
                    group_id,
                    artifact_id,
                    bom_version,
                )
            count += 1

    return count
