# pombast

**Validate that Maven Bill-of-Materials (BOM) components actually work together.**

---

## Status & Trajectory

> **Pre-alpha. Not yet suitable for general use.**
>
> Pombast is under active development and breaking changes are expected.
> APIs, CLI options, configuration format, and caching behavior may all
> change without notice until a stable 1.0 release.
>
> **Intended trajectory:** Pombast is being built as a principled replacement
> for the [pom-scijava](https://github.com/scijava/pom-scijava) *mega-melt*,
> the ad-hoc shell-script process that validates managed components before
> each pom-scijava release. The goal is to make BOM validation reproducible,
> configurable, and automatable outside of any single repository's CI
> infrastructure, and usable for any Maven BOM, not just SciJava's.

---

## What it does

Pombast provides two independent validation modes:

### `pombast melt` — holistic classpath check

Generates a single "mega-melt" POM that lists every BOM component as a direct
dependency, inheriting versions from the BOM's own `<dependencyManagement>`, and
runs Maven against it. Catches duplicate classes across the full BOM classpath
and SNAPSHOT dependencies without touching individual component source trees.

### `pombast smelt` — per-component build and test

For each filtered component:

1. Resolves source code via SCM metadata in the POM.
2. Rewrites the component POM to pin every dependency to the BOM-declared version.
3. Optionally tests binary compatibility of the already-published JAR against the
   pinned dependency set (catches runtime breakage without rebuilding from source).
4. Rebuilds from source and runs the test suite.
5. Reports success, failure, or error with timing and per-component build logs.

Both commands are independent and can be run separately or together in CI.

---

## Requirements

- Python 3.10+
- Maven (`mvn`) on `PATH`
- Git on `PATH`

System Java is not required — pombast auto-detects and downloads the right
version of Java per component via [jgo](https://github.com/scijava/jgo).

---

## Installation

As a command-line tool:

```bash
uv tool install git+https://github.com/scijava/pombast
```

As a dependency:

```bash
uv add git+https://github.com/scijava/pombast
```

---

## Quick start

```bash
# Validate BOM classpath holistically
pombast melt org.scijava:pom-scijava:37.0.0

# Build and test each component
pombast smelt org.scijava:pom-scijava:37.0.0

# Smelt only scijava-group artifacts
pombast smelt -i "org.scijava:*" org.scijava:pom-scijava:37.0.0

# Inject a candidate version change, build only affected components
pombast smelt -c "org.scijava:scijava-common:2.100.0" -p org.scijava:pom-scijava:37.0.0

# Validate a local BOM under development
pombast melt /path/to/local/bom
pombast smelt /path/to/local/bom
```

---

## CLI reference

`BOM` is a Maven `G:A:V` coordinate or a path to a local directory containing
a `pom.xml` that declares `<dependencyManagement>`.

### `pombast melt BOM`

Validate the full BOM classpath as a single mega-melt project.

| Option | Description |
|---|---|
| `-i, --include G:A` | Include only matching components (repeatable, wildcards OK) |
| `-e, --exclude G:A` | Exclude matching components (repeatable, wildcards OK) |
| `-r, --repository URL` | Additional Maven repository (repeatable) |
| `--config PATH` | Path to `pombast.toml` config file |
| `-o, --output-dir PATH` | Output directory (default: `pombast-output`) |
| `-f, --force` | Wipe output directory if it already exists |
| `--java-version N` | Java version to use when validating the BOM |
| `-v, --verbose` | Debug logging |

### `pombast smelt BOM`

Build and test each BOM component against its pinned dependencies.

| Option | Description |
|---|---|
| `-c, --change G:A:V` | Inject a version override (repeatable) |
| `-i, --include G:A` | Include only matching components (repeatable, wildcards OK) |
| `-e, --exclude G:A` | Exclude matching components (repeatable, wildcards OK) |
| `-r, --repository URL` | Additional Maven repository (repeatable) |
| `--config PATH` | Path to `pombast.toml` config file |
| `-o, --output-dir PATH` | Output directory (default: `pombast-output`) |
| `-p, --prune` | Only build components that depend on changed artifacts |
| `-f, --force` | Wipe output directory if it already exists |
| `-s, --skip-build` | Prepare source trees but skip actual builds |
| `--no-binary-test` | Skip binary compatibility testing |
| `--default-java N` | Default Java version for components with no declared version |
| `-v, --verbose` | Debug logging |

---

## Configuration file

Create a `pombast.toml` for reusable settings:

```toml
[common]
# Shared settings used by both smelt and melt.
default-java-version = 11
repositories = ["scijava.public:https://maven.scijava.org/content/groups/public"]
properties = {"skipSomePlugin" = "true"}

[smelt]
# Settings for the smelt (per-component build) command.
includes = ["org.scijava:*"]
excludes = ["org.scijava:legacy-*"]
skip-tests = ["org.example:legacy-lib"]

[remove-tests]
# Remove specific test classes before building (smelt only).
"org.example:flaky-component" = ["FlakyIntegrationTest"]

[components."org.example:component"]
# Override Java version for a specific component (smelt only).
"java-version" = 17

[melt]
# Settings for the melt (mega-melt BOM validation) command.
java-version = 11
template = "tests/mega-melt-template.xml"
excludes = ["org.example:problematic-artifact"]
```

Pass it with `--config pombast.toml`.

---

## Python API

```python
from pombast.config._settings import MeltConfig, PipelineConfig, PombastConfig
from pombast.core._melt_pipeline import MeltPipeline
from pombast.core._pipeline import Pipeline

cfg = PombastConfig.load("pombast.toml")

# Holistic classpath check
melt_result = MeltPipeline(MeltConfig(bom="org.scijava:pom-scijava:37.0.0", config=cfg)).run()
print("Melt:", "PASSED" if melt_result.success else "FAILED")

# Per-component builds
report = Pipeline(PipelineConfig(bom="org.scijava:pom-scijava:37.0.0", config=cfg)).run()
print(report.summary())
for result in report.failures:
    print(result.component.coordinate, result.status)
```

---

## How `melt` works

Pombast generates a throwaway `mega-melt/pom.xml` inside the output directory
that inherits from the BOM under test (via `<relativePath>`, no `mvn install`)
and lists every filtered component as a direct `<dependency>` with no explicit
`<version>` — versions are inherited from the BOM's `<dependencyManagement>`.
It then runs `mvn dependency:tree` and `mvn validate` against that POM.

Because the BOM is the parent, its enforcer rules apply: duplicate classes across
the full classpath are detected (via `banDuplicateClasses`), and SNAPSHOT
dependencies are rejected (via `requireReleaseDependencies`).

The BOM pom.xml is copied into the output directory and its `<version>` is
stamped to a synthetic non-SNAPSHOT value (`0-pombast`) so Maven and the
enforcer's `requireReleaseVersion` rule do not complain about a SNAPSHOT parent.
Nothing is written to `~/.m2/repository`.

If the BOM's enforcer requires certain POM elements (e.g., `<url>`,
`<developers>`, `<licenses>`), provide a `[mega-melt] template` pointing to a
POM template that supplies them. Pombast will splice in the correct `<parent>`
reference and `<dependencies>` block automatically.

---

## How `smelt` POM rewriting works

Pombast uses a two-pronged approach to enforce BOM versions regardless of what
a component's own POM declares:

1. **Inject dependency management** — the full BOM `<dependencyManagement>` is
   inserted directly into each component's POM, taking precedence over anything
   inherited from parent POMs.
2. **Hardcode dependency versions** — every `<dependency>` element that appears
   in the BOM has its `<version>` written in directly, overriding any property
   expressions or omitted-version inheritance.

This is intentionally aggressive: the goal is to test whether the BOM's
declared versions actually work, not whether the component happens to pull in
compatible versions through its own resolution logic.

---

## Caching

Pombast caches two things under `~/.cache/pombast/`:

- **`repos/`** — bare Git clones of component repositories, reused across runs.
- **`success/`** — fingerprints of successful builds. If a component's BOM
  fingerprint hasn't changed since the last successful build, it is skipped
  (unless the version is a SNAPSHOT).

---

## License

[Unlicense](https://unlicense.org/) — public domain.
