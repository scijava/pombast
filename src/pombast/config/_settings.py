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
class MegaMeltConfig:
    """Configuration for the mega-melt BOM validation phase."""

    java_version: int | None = None
    template: Path | None = None  # resolved absolute path to a template POM
    filter: FilterConfig = field(default_factory=FilterConfig)


@dataclass
class PombastConfig:
    """Configuration loaded from a pombast.toml file."""

    filter: FilterConfig = field(default_factory=FilterConfig)
    default_java: int | None = None
    repositories: list[str] = field(default_factory=list)
    skip_tests: list[str] = field(default_factory=list)
    remove_tests: dict[str, list[str]] = field(default_factory=dict)
    build_properties: dict[str, str] = field(default_factory=dict)
    component_overrides: dict[str, dict[str, object]] = field(default_factory=dict)
    mega_melt: MegaMeltConfig = field(default_factory=MegaMeltConfig)

    @classmethod
    def load(cls, path: Path) -> PombastConfig:
        """Load configuration from a pombast.toml file."""
        with open(path, "rb") as f:
            data = tomllib.load(f)

        filter_data = data.get("filter", {})
        filter_config = FilterConfig(
            includes=filter_data.get("includes", []),
            excludes=filter_data.get("excludes", []),
        )

        build_data = data.get("build", {})
        default_java = build_data.get("default-java-version")

        mega_melt_data = data.get("mega-melt", {})
        mega_melt_java = mega_melt_data.get("java-version")
        template_str = mega_melt_data.get("template")
        template_path = (path.parent / template_str).resolve() if template_str else None
        mm_filter_data = mega_melt_data.get("filter", {})
        mega_melt_config = MegaMeltConfig(
            java_version=int(mega_melt_java) if mega_melt_java is not None else None,
            template=template_path,
            filter=FilterConfig(
                includes=mm_filter_data.get("includes", []),
                excludes=mm_filter_data.get("excludes", []),
            ),
        )

        return cls(
            filter=filter_config,
            default_java=int(default_java) if default_java is not None else None,
            repositories=build_data.get("repositories", []),
            skip_tests=data.get("skip-tests", {}).get("components", []),
            remove_tests=data.get("remove-tests", {}),
            build_properties=build_data.get("properties", {}),
            component_overrides={k: v for k, v in data.get("components", {}).items()},
            mega_melt=mega_melt_config,
        )

    @classmethod
    def empty(cls) -> PombastConfig:
        """Return an empty configuration with all defaults."""
        return cls()


@dataclass
class PipelineConfig:
    """Configuration for a smelt (per-component build) pipeline run."""

    bom: str
    default_java: int | None = None
    changes: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)
    output_dir: Path = field(default_factory=lambda: Path("pombast-output"))
    success_cache_dir: Path | None = None
    prune: bool = False
    force: bool = False
    skip_build: bool = False
    test_binary: bool = True
    verbose: bool = False
    config: PombastConfig = field(default_factory=PombastConfig.empty)


@dataclass
class MeltConfig:
    """Configuration for a melt (mega-melt BOM validation) pipeline run."""

    bom: str
    repositories: list[str] = field(default_factory=list)
    output_dir: Path = field(default_factory=lambda: Path("pombast-output"))
    force: bool = False
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    default_java: int | None = None
    verbose: bool = False
    config: PombastConfig = field(default_factory=PombastConfig.empty)
