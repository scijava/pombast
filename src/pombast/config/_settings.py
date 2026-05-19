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
class StatusConfig:
    """Configuration for the status command."""

    rules: Path | None = None
    projects: Path | None = None
    badges: Path | None = None
    timestamps: Path | None = None
    html: Path | None = None
    header: Path | None = None
    footer: Path | None = None


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
    status: StatusConfig = field(default_factory=StatusConfig)

    @classmethod
    def load(cls, path: Path) -> PombastConfig:
        """Load configuration from a pombast.toml file."""
        with open(path, "rb") as f:
            data = tomllib.load(f)

        smelt_data = data.get("smelt", {})
        filter_config = FilterConfig(
            includes=smelt_data.get("includes", []),
            excludes=smelt_data.get("excludes", []),
        )

        common_data = data.get("common", {})
        default_java = common_data.get("default-java-version")

        melt_data = data.get("melt", {})
        melt_java = melt_data.get("java-version")
        template_str = melt_data.get("template")
        template_path = (path.parent / template_str).resolve() if template_str else None
        mega_melt_config = MegaMeltConfig(
            java_version=int(melt_java) if melt_java is not None else None,
            template=template_path,
            filter=FilterConfig(
                includes=melt_data.get("includes", []),
                excludes=melt_data.get("excludes", []),
            ),
        )

        def resolve(section: dict, key: str) -> Path | None:
            s = section.get(key)
            return (path.parent / s).resolve() if s else None

        status_data = data.get("status", {})
        status_config = StatusConfig(
            rules=resolve(status_data, "rules"),
            projects=resolve(status_data, "projects"),
            badges=resolve(status_data, "badges"),
            timestamps=resolve(status_data, "timestamps"),
            html=resolve(status_data, "html"),
            header=resolve(status_data, "header"),
            footer=resolve(status_data, "footer"),
        )

        return cls(
            filter=filter_config,
            default_java=int(default_java) if default_java is not None else None,
            repositories=common_data.get("repositories", []),
            skip_tests=smelt_data.get("skip-tests", []),
            remove_tests=data.get("remove-tests", {}),
            build_properties=common_data.get("properties", {}),
            component_overrides={k: v for k, v in data.get("components", {}).items()},
            mega_melt=mega_melt_config,
            status=status_config,
        )

    @classmethod
    def load_default(cls, explicit: Path | None) -> PombastConfig:
        """Load config from explicit path, ./pombast.toml, or defaults."""
        if explicit is not None:
            return cls.load(explicit)
        auto = Path("pombast.toml")
        if auto.exists():
            return cls.load(auto)
        return cls.empty()

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
