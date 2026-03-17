"""Configuration loading and pipeline settings."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class FilterConfig:
    """Include/exclude patterns from config file."""

    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)


@dataclass
class VersionPinsConfig:
    """Version pin overrides from config file."""

    aliases: dict[str, str] = field(default_factory=dict)
    remove_duplicates: dict[str, str] = field(default_factory=dict)


@dataclass
class BombastConfig:
    """Configuration loaded from a bombast.toml file."""

    filter: FilterConfig = field(default_factory=FilterConfig)
    version_pins: VersionPinsConfig = field(default_factory=VersionPinsConfig)
    skip_tests: list[str] = field(default_factory=list)
    remove_tests: dict[str, list[str]] = field(default_factory=dict)
    build_properties: dict[str, str] = field(default_factory=dict)
    component_overrides: dict[str, dict[str, object]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> BombastConfig:
        """Load configuration from a bombast.toml file."""
        with open(path, "rb") as f:
            data = tomllib.load(f)

        filter_data = data.get("filter", {})
        filter_config = FilterConfig(
            includes=filter_data.get("includes", []),
            excludes=filter_data.get("excludes", []),
        )

        pins_data = data.get("version-pins", {})
        pins_config = VersionPinsConfig(
            aliases=pins_data.get("aliases", {}),
            remove_duplicates=pins_data.get("remove-duplicates", {}),
        )

        build_data = data.get("build", {})

        return cls(
            filter=filter_config,
            version_pins=pins_config,
            skip_tests=data.get("skip-tests", {}).get("components", []),
            remove_tests=data.get("remove-tests", {}),
            build_properties=build_data.get("properties", {}),
            component_overrides={
                k: v for k, v in data.get("components", {}).items()
            },
        )

    @classmethod
    def empty(cls) -> BombastConfig:
        """Return an empty configuration with all defaults."""
        return cls()


@dataclass
class PipelineConfig:
    """Full configuration for a pipeline run, combining CLI args and config file."""

    bom: str
    changes: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)
    output_dir: Path = field(default_factory=lambda: Path("bombast-output"))
    prune: bool = False
    force: bool = False
    skip_build: bool = False
    verbose: bool = False
    config: BombastConfig = field(default_factory=BombastConfig.empty)
