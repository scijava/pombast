"""Generate Maven settings.xml with version pins for all BOM components."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from bombast.config._settings import VersionPinsConfig
from bombast.core._component import Component

_SETTINGS_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<settings xmlns="http://maven.apache.org/SETTINGS/1.1.0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.1.0 \
https://maven.apache.org/xsd/settings-1.1.0.xsd">
  <profiles>
    <profile>
      <id>version-pins</id>
      <activation>
        <activeByDefault>true</activeByDefault>
      </activation>
      <properties>
"""

_SETTINGS_FOOTER = """\
      </properties>
    </profile>
  </profiles>
</settings>
"""


def generate_version_pins(
    components: list[Component],
    *,
    changes: list[Component] | None = None,
    extra_properties: dict[str, str] | None = None,
    config: VersionPinsConfig | None = None,
) -> str:
    """Generate Maven settings.xml content with version-pinning properties.

    For each component, generates two version properties:
    - <groupId.artifactId.version>V</groupId.artifactId.version>
    - <artifactId.version>V</artifactId.version>

    Changed components (from -c flag) override the BOM version.

    Args:
        components: All managed components from the BOM.
        changes: Components with overridden versions (from -c flag).
        extra_properties: Additional properties to include (e.g., build.properties).
        config: Version pins configuration for aliases and dedup.

    Returns:
        Complete Maven settings.xml content as a string.
    """
    if config is None:
        config = VersionPinsConfig()

    # Build version map: G:A → version, with changes taking precedence.
    versions: dict[str, str] = {}
    for c in components:
        versions[c.ga] = c.version

    if changes:
        for c in changes:
            versions[c.ga] = c.version

    # Generate property lines.
    props: dict[str, str] = {}

    for ga, version in sorted(versions.items()):
        group, artifact = ga.split(":", 1)
        # Long form: groupId.artifactId.version
        long_key = f"{group}.{artifact}.version"
        props[long_key] = version

        # Short form: artifactId.version
        short_key = f"{artifact}.version"
        # Check for duplicate short keys — if configured, keep only the
        # specified group's value; otherwise, keep whichever we see last.
        if short_key in config.remove_duplicates:
            preferred_group = config.remove_duplicates[short_key]
            if group != preferred_group:
                # Skip this short key — another group owns it.
                pass
            else:
                props[short_key] = version
        else:
            props[short_key] = version

    # Add aliases.
    for alias, canonical in config.aliases.items():
        if canonical in props:
            props[alias] = props[canonical]

    # Add extra properties.
    if extra_properties:
        props.update(extra_properties)

    # Build XML.
    lines = []
    for key in sorted(props):
        value = escape(props[key])
        lines.append(f"        <{key}>{value}</{key}>")

    return _SETTINGS_HEADER + "\n".join(lines) + "\n" + _SETTINGS_FOOTER


def write_version_pins(
    path: Path,
    components: list[Component],
    **kwargs,
) -> Path:
    """Generate and write version-pins.xml to the given path.

    Returns the path written to.
    """
    content = generate_version_pins(components, **kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path
