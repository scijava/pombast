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

Given a Maven BOM (Bill of Materials) coordinate, pombast:

1. Loads all managed components from the BOM.
2. Resolves source code for each component via SCM metadata in the POM.
3. Rewrites component POMs to pin every dependency to the version declared in
   the BOM, overriding whatever the component's own POM or parent chain says.
4. Optionally tests binary compatibility of the already-published JARs against
   the pinned dependency set (catches runtime breakage without rebuilding).
5. Rebuilds each component from source and runs its test suite.
6. Reports which components succeeded, failed, or errored, with timing and
   build logs saved per component.

The result is a clear picture of whether a BOM's declared versions are mutually
consistent — before that BOM is shipped.

---

## Requirements

- Python 3.10+
- Maven (`mvn`) on `PATH`
- Git on `PATH`

System Java is not required—pombast auto-detects and downloads the right
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
# Validate all components in pom-scijava 37.0.0
pombast org.scijava:pom-scijava:37.0.0

# Validate only scijava-group artifacts
pombast -i "org.scijava:*" org.scijava:pom-scijava:37.0.0

# Inject a candidate version change, and validate only affected components
pombast -c "org.scijava:scijava-common:2.100.0" -p org.scijava:pom-scijava:37.0.0

# Validate a local BOM under development
pombast /path/to/local/bom
```

---

## CLI reference

```
pombast [OPTIONS] BOM
```

`BOM` is a Maven `G:A:V` coordinate or a path to a local directory containing
a `pom.xml` that declares `<dependencyManagement>`.

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
| `--min-java N` | Minimum Java version floor for all components |
| `-v, --verbose` | Debug logging |

---

## Configuration file

Create a `pombast.toml` for reusable settings:

```toml
[filter]
includes = ["org.scijava:*"]
excludes = ["org.scijava:legacy-*"]

[build]
min-java-version = 11
properties = {"skipSomePlugin" = "true"}

[skip-tests]
# Run build but skip tests for known-broken components
components = ["org.example:legacy-lib"]

[remove-tests]
# Remove specific test classes before building
"org.example:flaky-component" = ["FlakyIntegrationTest"]

[components."org.example:component"]
# Override Java version for a specific component
"java-version" = 17
```

Pass it with `--config pombast.toml`.

---

## Python API

```python
import pombast

report = pombast.validate("org.scijava:pom-scijava:37.0.0")
print(report.summary())

for result in report.failures:
    print(result.component.coordinate, result.status)
```

---

## How POM rewriting works

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
