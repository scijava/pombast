"""Generate and validate a mega-melt POM for holistic BOM classpath checking."""

from __future__ import annotations

import logging
import shutil
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from pombast.maven._pom_rewriter import patch_pom_urls
from pombast.util._process import run_maven

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.core._component import Component

_log = logging.getLogger(__name__)
_NS = "http://maven.apache.org/POM/4.0.0"

# Synthetic non-SNAPSHOT version stamped onto the BOM copy so Maven and the
# enforcer's requireReleaseVersion rule don't complain about a SNAPSHOT parent.
_SYNTHETIC_VERSION = "0-pombast"


def prepare_mega_melt(
    bom_pom_path: Path,
    mega_melt_dir: Path,
    components: list[Component],
    repositories: dict[str, str],
    template_path: Path | None = None,
) -> Path:
    """Set up the mega-melt directory and write its pom.xml.

    Copies the BOM pom.xml into mega_melt_dir/bom/pom.xml, replaces its
    <version> with a synthetic non-SNAPSHOT value so the enforcer does not
    reject a SNAPSHOT parent, then generates mega_melt_dir/pom.xml that
    inherits from it via <relativePath>.  No mvn install; no ~/.m2 writes.

    Returns the path to the generated mega-melt pom.xml.
    """
    mega_melt_dir.mkdir(parents=True, exist_ok=True)

    # Copy the BOM POM and stamp it with the synthetic version.
    bom_copy_dir = mega_melt_dir / "bom"
    bom_copy_dir.mkdir(parents=True, exist_ok=True)
    parent_pom = bom_copy_dir / "pom.xml"
    shutil.copy2(bom_pom_path, parent_pom)
    patch_pom_urls(parent_pom)

    ET.register_namespace("", _NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    tree = ET.parse(parent_pom)
    root = tree.getroot()

    group_elem = root.find(f"{{{_NS}}}groupId")
    if group_elem is None:
        # groupId is commonly inherited from <parent> rather than declared directly.
        group_elem = root.find(f"{{{_NS}}}parent/{{{_NS}}}groupId")
    artifact_elem = root.find(f"{{{_NS}}}artifactId")
    version_elem = root.find(f"{{{_NS}}}version")
    if group_elem is None or artifact_elem is None:
        raise ValueError(f"BOM POM missing groupId or artifactId: {bom_pom_path}")

    bom_group = (group_elem.text or "").strip()
    bom_artifact = (artifact_elem.text or "").strip()
    if version_elem is None:
        version_elem = ET.SubElement(root, f"{{{_NS}}}version")
    version_elem.text = _SYNTHETIC_VERSION
    ET.indent(tree, space="\t")
    tree.write(parent_pom, xml_declaration=True, encoding="UTF-8")

    # Generate the mega-melt pom.xml (from template or from scratch).
    mega_melt_pom = mega_melt_dir / "pom.xml"
    if template_path is not None:
        _write_mega_melt_pom_from_template(
            template_path=template_path,
            pom_path=mega_melt_pom,
            components=components,
        )
    else:
        _write_mega_melt_pom(
            pom_path=mega_melt_pom,
            parent_group=bom_group,
            parent_artifact=bom_artifact,
            components=components,
            repositories=repositories,
        )
    _log.info("Generated mega-melt POM with %d components", len(components))
    return mega_melt_pom


def _write_mega_melt_pom(
    pom_path: Path,
    parent_group: str,
    parent_artifact: str,
    components: list[Component],
    repositories: dict[str, str],
) -> None:
    """Write the mega-melt pom.xml."""
    ET.register_namespace("", _NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

    project = ET.Element(
        f"{{{_NS}}}project",
        attrib={
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:schemaLocation": (
                "http://maven.apache.org/POM/4.0.0 "
                "https://maven.apache.org/xsd/maven-4.0.0.xsd"
            ),
        },
    )

    _sub(project, "modelVersion", "4.0.0")

    parent = ET.SubElement(project, f"{{{_NS}}}parent")
    _sub(parent, "groupId", parent_group)
    _sub(parent, "artifactId", parent_artifact)
    _sub(parent, "version", _SYNTHETIC_VERSION)
    _sub(parent, "relativePath", "bom/pom.xml")

    _sub(project, "artifactId", "mega-melt")
    _sub(project, "version", "0-pombast")
    _sub(project, "packaging", "pom")
    _sub(project, "name", "Mega Melt")
    _sub(project, "description", "All BOM components as direct dependencies")

    # Non-central repositories only — Central is implicit in Maven.
    non_central = {
        rid: url
        for rid, url in repositories.items()
        if url != "https://repo1.maven.org/maven2"
    }
    if non_central:
        repos_elem = ET.SubElement(project, f"{{{_NS}}}repositories")
        for repo_id, url in non_central.items():
            repo = ET.SubElement(repos_elem, f"{{{_NS}}}repository")
            _sub(repo, "id", repo_id)
            _sub(repo, "url", url)

    # List every component as a dependency.  No <version> here — Maven
    # inherits them from the parent's <dependencyManagement>.
    deps_elem = ET.SubElement(project, f"{{{_NS}}}dependencies")
    for comp in components:
        dep = ET.SubElement(deps_elem, f"{{{_NS}}}dependency")
        _sub(dep, "groupId", comp.group)
        _sub(dep, "artifactId", comp.name)

    tree = ET.ElementTree(project)
    ET.indent(tree, space="\t")
    tree.write(pom_path, xml_declaration=True, encoding="UTF-8")


def _write_mega_melt_pom_from_template(
    template_path: Path,
    pom_path: Path,
    components: list[Component],
) -> None:
    """Write the mega-melt pom.xml by adapting a template POM.

    Updates <parent><version> to the synthetic value, adds/replaces
    <parent><relativePath>, updates the project <version>, and replaces
    the <dependencies> block with the given component list.
    """
    ET.register_namespace("", _NS)
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

    tree = ET.parse(template_path)
    root = tree.getroot()

    parent_elem = root.find(f"{{{_NS}}}parent")
    if parent_elem is None:
        raise ValueError(f"Template POM has no <parent> element: {template_path}")

    version_elem = parent_elem.find(f"{{{_NS}}}version")
    if version_elem is None:
        version_elem = ET.SubElement(parent_elem, f"{{{_NS}}}version")
    version_elem.text = _SYNTHETIC_VERSION

    rel_path_elem = parent_elem.find(f"{{{_NS}}}relativePath")
    if rel_path_elem is None:
        rel_path_elem = ET.SubElement(parent_elem, f"{{{_NS}}}relativePath")
    rel_path_elem.text = "bom/pom.xml"

    proj_version_elem = root.find(f"{{{_NS}}}version")
    if proj_version_elem is not None:
        proj_version_elem.text = "0-pombast"

    existing_deps = root.find(f"{{{_NS}}}dependencies")
    if existing_deps is not None:
        root.remove(existing_deps)

    if components:
        deps_elem = ET.SubElement(root, f"{{{_NS}}}dependencies")
        for comp in components:
            dep = ET.SubElement(deps_elem, f"{{{_NS}}}dependency")
            _sub(dep, "groupId", comp.group)
            _sub(dep, "artifactId", comp.name)

    ET.indent(tree, space="\t")
    tree.write(pom_path, xml_declaration=True, encoding="UTF-8")


def run_mega_melt_validation(
    mega_melt_dir: Path,
    java_home: Path | None = None,
    extra_properties: dict[str, str] | None = None,
    settings: Path | None = None,
) -> tuple[bool, Path, Path]:
    """Run mega-melt validation.

    Runs dependency:tree (catches broken resolution) then clean package
    (triggers the BOM's enforcer rules, including banDuplicateClasses).

    Returns:
        (success, tree_log_path, build_log_path)
    """
    tree_log = mega_melt_dir / "dependency-tree.log"
    build_log = mega_melt_dir / "validation.log"

    _log.info("Mega-melt: running dependency:tree")
    tree_result = run_maven(
        ["dependency:tree"],
        cwd=mega_melt_dir,
        java_home=java_home,
        extra_properties=extra_properties,
        log_path=tree_log,
        skip_enforcer=False,
        settings=settings,
    )
    if tree_result.returncode != 0:
        _log.warning("Mega-melt dependency:tree FAILED — see %s", tree_log)
        return False, tree_log, build_log

    _log.info("Mega-melt: running validate")
    build_result = run_maven(
        ["validate"],
        cwd=mega_melt_dir,
        java_home=java_home,
        extra_properties=extra_properties,
        log_path=build_log,
        skip_enforcer=False,
        settings=settings,
    )
    success = build_result.returncode == 0
    level = _log.info if success else _log.warning
    level(
        "Mega-melt validation: %s",
        "SUCCESS" if success else f"FAILURE — see {build_log}",
    )  # type: ignore[operator]
    return success, tree_log, build_log


def _sub(parent: ET.Element, tag: str, text: str) -> ET.Element:
    elem = ET.SubElement(parent, f"{{{_NS}}}{tag}")
    elem.text = text
    return elem
