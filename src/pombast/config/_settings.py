"""Configuration loading and pipeline settings."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _parse_role_value(value: object, default: str) -> list[str]:
    """Coerce a TOML role value (str or list[str]) to list[str]."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return [default]


def parse_repo_spec(spec: str, fallback_id: str) -> tuple[str, str]:
    """Parse 'id=url' or bare 'url'; return (repo_id, url)."""
    name, sep, url = spec.partition("=")
    return (name, url) if sep else (fallback_id, spec)


def parse_repo_specs(specs: list[str]) -> dict[str, str]:
    """Parse a list of 'id=url' or bare 'url' strings into a dict."""
    repos: dict[str, str] = {}
    for i, spec in enumerate(specs):
        repo_id, url = parse_repo_spec(spec, f"repo{i}")
        repos[repo_id] = url
    return repos


@dataclass
class FilterConfig:
    """Include/exclude patterns from config file."""

    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)


_TEAM_ROLE_KEYS = ("lead", "developer", "debugger", "reviewer", "support", "maintainer")


@dataclass
class TeamConfig:
    """Configuration for the team command, including role mappings."""

    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    output: Path | None = None
    header: Path | None = None
    footer: Path | None = None
    lead: list[str] = field(default_factory=lambda: ["lead"])
    developer: list[str] = field(default_factory=lambda: ["developer"])
    debugger: list[str] = field(default_factory=lambda: ["debugger"])
    reviewer: list[str] = field(default_factory=lambda: ["reviewer"])
    support: list[str] = field(default_factory=lambda: ["support"])
    maintainer: list[str] = field(default_factory=lambda: ["maintainer"])

    def role_mapping(self) -> dict[str, list[str]]:
        """Return {semantic_key: [pom_role_strings]} for all role keys."""
        return {key: getattr(self, key) for key in _TEAM_ROLE_KEYS}


@dataclass
class StatusConfig:
    """Configuration for the status command."""

    rules: Path | None = None
    projects: Path | None = None
    timestamps: Path | None = None
    smelt: Path | None = None  # smelt.json to overlay compatibility columns
    output: Path | None = None
    header: Path | None = None
    footer: Path | None = None
    nexus_base: str = ""
    default_ci_badge: str = "build"
    cuttable: list[str] = field(default_factory=list)
    # Highest JVM the BOM commits to supporting at runtime. A candidate version
    # whose effective bytecode floor exceeds this is classified "excluded" (it
    # would need a newer JVM than the BOM targets) rather than recommended.
    runtime_cap: int = 21


@dataclass
class BadgesConfig:
    """Configuration for the badges command."""

    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    output: Path | None = None  # where to write badges.json


@dataclass
class MegaMeltConfig:
    """Configuration for the mega-melt BOM validation phase."""

    java_version: int | None = None
    template: Path | None = None  # resolved absolute path to a template POM
    filter: FilterConfig = field(default_factory=FilterConfig)
    maven_properties: dict[str, str] = field(default_factory=dict)


@dataclass
class PombastConfig:
    """Configuration loaded from a pombast.toml file."""

    filter: FilterConfig = field(default_factory=FilterConfig)
    default_java: int | None = None
    repositories: dict[str, str] = field(default_factory=dict)
    smelt_output: Path | None = None  # where `smelt` writes its JSON report
    skip_tests: list[str] = field(default_factory=list)
    remove_tests: dict[str, list[str]] = field(default_factory=dict)
    build_properties: dict[str, str] = field(default_factory=dict)
    component_overrides: dict[str, dict[str, object]] = field(default_factory=dict)
    mega_melt: MegaMeltConfig = field(default_factory=MegaMeltConfig)
    status: StatusConfig = field(default_factory=StatusConfig)
    badges: BadgesConfig = field(default_factory=BadgesConfig)
    team: TeamConfig = field(default_factory=TeamConfig)

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
            maven_properties=melt_data.get("properties", {}),
        )

        def resolve(section: dict, key: str) -> Path | None:
            s = section.get(key)
            return (path.parent / s).resolve() if s else None

        status_data = data.get("status", {})
        status_config = StatusConfig(
            rules=resolve(status_data, "rules"),
            projects=resolve(status_data, "projects"),
            timestamps=resolve(status_data, "timestamps"),
            smelt=resolve(status_data, "smelt"),
            default_ci_badge=status_data.get("default-ci-badge", "build"),
            output=resolve(status_data, "output"),
            header=resolve(status_data, "header"),
            footer=resolve(status_data, "footer"),
            nexus_base=status_data.get("nexus-base", ""),
            cuttable=status_data.get("cuttable", []),
            runtime_cap=int(status_data.get("runtime-cap", 21)),
        )

        badges_data = data.get("badges", {})
        badges_config = BadgesConfig(
            includes=badges_data.get("includes", []),
            excludes=badges_data.get("excludes", []),
            output=resolve(badges_data, "output"),
        )

        team_data = data.get("team", {})
        team_config = TeamConfig(
            includes=team_data.get("includes", []),
            excludes=team_data.get("excludes", []),
            output=resolve(team_data, "output"),
            header=resolve(team_data, "header"),
            footer=resolve(team_data, "footer"),
            **{
                key: _parse_role_value(team_data[key], key)
                for key in _TEAM_ROLE_KEYS
                if key in team_data
            },
        )

        return cls(
            filter=filter_config,
            default_java=int(default_java) if default_java is not None else None,
            repositories=parse_repo_specs(common_data.get("repositories", [])),
            smelt_output=resolve(smelt_data, "output"),
            skip_tests=smelt_data.get("skip-tests", []),
            remove_tests=data.get("remove-tests", {}),
            build_properties=common_data.get("properties", {}),
            component_overrides={k: v for k, v in data.get("components", {}).items()},
            mega_melt=mega_melt_config,
            status=status_config,
            badges=badges_config,
            team=team_config,
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
    repositories: dict[str, str] = field(default_factory=dict)
    output_dir: Path = field(default_factory=lambda: Path("pombast-output"))
    success_cache_dir: Path | None = None
    prune: bool = False
    force: bool = False
    skip_build: bool = False
    test_binary: bool = True
    maven_properties: dict[str, str] = field(default_factory=dict)
    verbose: bool = False
    config: PombastConfig = field(default_factory=PombastConfig.empty)


@dataclass
class MeltConfig:
    """Configuration for a melt (mega-melt BOM validation) pipeline run."""

    bom: str
    repositories: dict[str, str] = field(default_factory=dict)
    output_dir: Path = field(default_factory=lambda: Path("pombast-output"))
    force: bool = False
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    default_java: int | None = None
    maven_properties: dict[str, str] = field(default_factory=dict)
    verbose: bool = False
    config: PombastConfig = field(default_factory=PombastConfig.empty)
