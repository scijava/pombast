# pombast

[![Build Status](https://github.com/scijava/pombast/actions/workflows/build.yml/badge.svg)](https://github.com/scijava/pombast/actions/workflows/build.yml)

**A toolkit for working with Maven Bill-of-Materials (BOM) POMs.**

---

## Status

> **Beta.** Pombast is usable, but APIs, CLI options, configuration format,
> and caching behavior may still change before a stable 1.0 release.

Pombast is designed to work with any Maven BOM. But it was built for and is in
production use with the [SciJava](https://scijava.org/) Bill of Materials,
[pom-scijava](https://github.com/scijava/pom-scijava).
Public resources powered by it include:

- **pom-scijava CI** — validates the managed components before each release.
- **[status.scijava.org](https://status.scijava.org/)** — release and vetting
  status, CI badges and developer accountability across all managed components.
- **[javadoc.scijava.org](https://javadoc.scijava.org/)** — cross-linked
  javadoc for the whole BOM.

---

## What it does

Pombast is a collection of tools that all operate on the set of components
managed by a BOM. Its major functions are:

- **`pombast melt`** — holistic classpath check across the whole BOM.
- **`pombast smelt`** — per-component build and test against pinned versions.
- **`pombast javadoc`** — generate a browsable, cross-linked javadoc site +
  unioned index from each component's published `-javadoc` JAR (or sources).
- **`pombast status`** — HTML report of each component's release/vetting status.
- **`pombast badges`** — fetch CI badge status for each component.
- **`pombast team`** — developer accountability report across components.

The two validation modes are independent and can be run separately or together
in CI:

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

`BOM` is a Maven `G:A:V` coordinate or a path to a local directory
containing a `pom.xml` that declares `<dependencyManagement>`.
It is optional and defaults to `.` (the current directory).

Every command writes its primary artifact to `-o, --output PATH`. Working build
directories use `--build-dir`. Output paths can also be set in `pombast.toml`
(see below), so a typical run needs no flags at all.

### `pombast melt BOM`

Validate the full BOM classpath as a single mega-melt project.

| Option | Description |
|---|---|
| `-i, --include G:A` | Include only matching components (repeatable, wildcards OK) |
| `-e, --exclude G:A` | Exclude matching components (repeatable, wildcards OK) |
| `-r, --repository URL` | Additional Maven repository (repeatable) |
| `--config PATH` | Path to `pombast.toml` config file |
| `--build-dir PATH` | Working directory for builds (default: `target/pombast`) |
| `-f, --force` | Wipe build directory if it already exists |
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
| `--build-dir PATH` | Working directory for builds (default: `target/pombast`) |
| `-o, --output PATH` | Write smelt results as JSON to this file (or `[smelt] output`) |
| `-p, --prune` | Only build components that depend on changed artifacts |
| `-f, --force` | Wipe build directory if it already exists |
| `-s, --skip-build` | Prepare source trees but skip actual builds |
| `--no-binary-test` | Skip binary compatibility testing |
| `--default-java N` | Default Java version for components with no declared version |
| `-v, --verbose` | Debug logging |

### `pombast javadoc BOM`

Unpack each component's `-javadoc` classifier JAR into `{output}/{g}/{a}/{v}/`
and assemble a unioned index for the BOM itself at
`{output}/{bom-g}/{bom-a}/{bom-v}/`. The union is a single, fast `javadoc -link`
target: its class URLs 301-redirect to the owning component, so the `javadoc`
tool fetches one small `element-list` instead of one per dependency. Union paths
are keyed by the class's flat path (`ij/ImagePlus.html`), matching the union's
flat `element-list`, while redirects target the real, possibly module-nested,
page (`ij/ij/ImagePlus.html`).

Component javadoc is cached per G:A:V, so composing a multi-version site is a
matter of invoking the command once per BOM; already-unpacked releases are
re-used rather than re-extracted. [javadoc.scijava.org] is built this way.

**Javadoc from sources.** Where a component publishes no `-javadoc` JAR, or
only an empty stub (as some projects do to satisfy Maven Central's rules),
pombast generates its javadoc from the `-sources` JAR instead, with JDK 21's
`javadoc` run as leniently as it allows (doclint off, source errors ignored),
the component's resolved dependency JARs on the classpath, and `-linkoffline`
links to each dependency's javadoc in the tree. Sources with nothing to
document (e.g. only Kotlin) count as missing, not as errors.

**Named unions.** `[javadoc.unions]` defines unions over subsets of the BOM
(e.g. `"net.imglib2" = ["net.imglib2:*"]`), each built like the BOM's own union
at `{output}/{bom-g}/{bom-a}/{bom-v}/{name}/`: a `-link` target and landing page
per project. A name must contain a `.` or `-`, which no Java package directory
can, so it never shadows a class path of the enclosing union.

**Site-wide maps.** After every run, pombast regenerates three `key value` maps
at the root of the tree from everything on disk: `redirects.map` (every union
path, across all BOM versions, to its component page), `latest.map` (each G:A to
its newest release, backing a floating `/{g}/{a}/latest/` alias), and
`latest-fallback.map` (union paths the newest union dropped, to the newest older
union that has them, so removed classes keep resolving). They are the input
format of Apache's RewriteMap; convert them with `httxt2dbm` for production.

**Repository load.** A run resolves the full dependency closure of every managed
component and probes for optional classifiers, so pombast takes care not to
hammer Maven repositories: requests to each repository are spaced at least
0.1 s apart, 404s are remembered for 30 days (for good on Maven Central, whose
releases are immutable), requests identify pombast in their User-Agent, a run
stops at the first 401/403 instead of misreading a block as missing artifacts,
and its summary reports how many requests it made per host.

**Crosslinking.** After unpacking, each component's HTML is rewritten so class
references resolve to the *exact versioned* javadoc of that component's
dependencies — the versions jgo actually resolves from the component's own POM,
**not** the BOM's managed versions. This repairs the irreproducible links older
SciJava-built javadoc baked in (flat `/SciJava/…`, `/ImgLib2/…` prefixes) and
adds links to classes that were never linked at all (their fully-qualified name
was embedded as plain text). To make those targets exist, each component's full
resolved dependency closure is unpacked into the tree too (cached per G:A:V), and
**every unpacked component is itself crosslinked** — not just the BOM's managed
ones — so links stay reproducible even when a reader browses into a dependency's
pages. Crosslinking is cached via a per-component marker and re-runs under
`--force`.

Link targets point at each class's *real* on-disk location in the resolved
version. That matters for **modular (Java 9+) javadoc**, which nests classes under
their JPMS module (e.g. ImageJ's module `ij` puts `ij.plugin.PlugIn` at
`ij/ij/plugin/PlugIn.html`): pombast reads each unpacked dependency's own
`element-list` to key classes by their true FQCN while linking to the actual
(possibly module-doubled) path, so references resolve whether the resolved version
was built modular or not.

`java.*` / `javax.*` (JDK) references have no Maven artifact to point at. A link
is recognized as a JDK link by the *shape* of its target (its class is a JDK
class) rather than by matching known hosts, so every baked-in form — absolute
Oracle/sun URLs across eras, modular `.../java.base/…` paths, the `/Java{N}/`
proxy — is normalized the same way onto a configured API base at the component's
**true** target Java version (read from its resolved `maven.compiler.release` /
`scijava.jvm.version`), not the often-stale version baked into the original link.
For Java 9+ the link is module-qualified (`…/java.base/java/lang/Object.html`)
using the package→module map from the base's own `element-list` — the same file
`javadoc -link` consumes — so no module table is bundled or can drift; Java 8
bases (flat `package-list`, no modules) stay module-less. See
`jdk-api-url-template` / `jdk-api-base-urls` below. The default template
`/Java{java}/` reproduces SciJava's proxied prefixes.

| Option | Description |
|---|---|
| `-i, --include G:A` | Include only matching components (repeatable, wildcards OK) |
| `-e, --exclude G:A` | Exclude matching components (repeatable, wildcards OK) |
| `-r, --repository URL` | Additional Maven repository (repeatable) |
| `--config PATH` | Path to `pombast.toml` config file |
| `-o, --output PATH` | Javadoc site output directory (or `[javadoc] output`) |
| `--url-prefix URL` | Absolute prefix for the deployed site (e.g. `https://javadoc.scijava.org`) |
| `--redirect-format FMT` | `rewritemap` (scales, needs server config) or `redirectmatch` (self-contained `.htaccess`) |
| `--workers N` | Parallel resolve/unpack/crosslink workers (default: 8) |
| `-f, --force` | Re-extract and re-crosslink components even if already processed |
| `-v, --verbose` | Debug logging |

The canonical redirect artifact is always `redirects.tsv` (server-agnostic
`union-path <TAB> component-path`); `--redirect-format` only chooses which
web-server config is rendered alongside it.

Links are site-relative unless `--url-prefix` is given. Since components are
cached per G:A:V and never rewritten, pick one style for a tree and keep it.

**Publishing.** `bin/publish-javadoc.sh` publishes a build tree atomically:

```bash
bin/publish-javadoc.sh [-n] [-k KEEP] [-s SITE] BUILD RELEASES LIVE
```

It hard-links `BUILD` into a timestamped snapshot under `RELEASES`, optionally
lays a site's own static files (front page, styles) from `SITE` over it,
converts the site-wide maps to SDBM, and switches the `LIVE` symlink (the web
server's document root) to the snapshot in a single rename, keeping the newest
`KEEP` (default 3). Unchanged files are shared, so a snapshot costs little more
than its directories; this is safe because pombast never modifies a file in
place, writing a new one and renaming it over the old. `-n` is a dry run.

With Apache, the maps back rules like these (see [javadoc.scijava.org] for a
complete, tested setup):

```apache
RewriteMap javadoc  "dbm=sdbm:/var/www/site/redirects.map.db"
RewriteMap latest   "dbm=sdbm:/var/www/site/latest.map.db"
RewriteMap latestfb "dbm=sdbm:/var/www/site/latest-fallback.map.db"

# /{g}/{a}/latest/... floats, so 302.
RewriteCond ${latestfb:$1} ^(/.+)$
RewriteRule ^(/[^/]+/[^/]+/latest/.+)$ %1 [R=302,L,NE]
RewriteCond ${latest:$1/$2} ^(.+)$
RewriteRule ^/([^/]+)/([^/]+)/latest(?:/(.*))?$ /$1/$2/%1/$3 [R=302,L,NE]

# Union paths -> the owning component's page.
RewriteCond ${javadoc:$1} ^(/.+)$
RewriteRule ^(/[^/]+/[^/]+/[^/]+/.+)$ %1 [R=301,L,NE]
```

---

## Configuration file

Create a `pombast.toml` for reusable settings:

```toml
[common]
# Shared settings used by both smelt and melt.
default-java-version = 11
repositories = ["scijava.public=https://maven.scijava.org/content/groups/public"]
properties = {"skipSomePlugin" = "true"}

[smelt]
# Settings for the smelt (per-component build) command.
includes = ["org.scijava:*"]
excludes = ["org.scijava:legacy-*"]
skip-tests = ["org.example:legacy-lib"]
output = "../status.scijava.org/smelt.json"  # where `smelt` writes its JSON report

[remove-tests]
# Delete specific test classes from a component's checkout before building
# (smelt only). Keyed by "groupId:artifactId"; each entry is a list of
# fully-qualified test class names. Fully-qualified names are required so that
# identically-named classes in different packages are not removed by accident.
# Each name maps to src/test/java/<package path>/<ClassName>.java.
"org.example:flaky-component" = ["org.example.flaky.FlakyIntegrationTest"]

[components."org.example:component"]
# Override Java version for a specific component (smelt only).
"java-version" = 17

[melt]
# Settings for the melt (mega-melt BOM validation) command.
java-version = 11
template = "tests/mega-melt-template.xml"
excludes = ["org.example:problematic-artifact"]

[status]
# Settings for the status command.
rules = "rules.xml"
projects = "projects.txt"
timestamps = "timestamps.txt"
smelt = "../status.scijava.org/smelt.json"   # smelt.json to overlay (input)
output = "../status.scijava.org/status.html"
header = "header.html"
footer = "footer.html"

[badges]
# Settings for the badges command.
output = "../status.scijava.org/badges.json"

[team]
# Settings for the team command.
output = "../status.scijava.org/team.html"      # team.json is written alongside it

[javadoc]
# Settings for the javadoc command.
output = "target/pombast/javadoc"               # javadoc site output directory (build tree)
redirect-format = "rewritemap"                  # or "redirectmatch" for a self-contained .htaccess
# JDK (java.*) link handling. The template is formatted with {java} (the Java
# version); the default below reproduces SciJava's proxied /Java8/ prefixes.
jdk-api-url-template = "/Java{java}/"
# Explicit per-version bases override the template (Oracle changes its URL
# structure between releases). Keyed "j8", "j21", …:
[javadoc.jdk-api-base-urls]
j8 = "https://docs.oracle.com/javase/8/docs/api/"
j21 = "https://docs.oracle.com/en/java/javase/21/docs/api/"
# Named unions over parts of the BOM: name -> G:A patterns of its members.
[javadoc.unions]
"net.imglib2" = ["net.imglib2:*"]
"bio-formats" = ["ome:*", "org.openmicroscopy:*"]
```

If `pombast.toml` exists in the current directory it is loaded automatically.
Pass `--config PATH` to use a different file.

With output paths configured this way, the full status pipeline needs no flags:

```bash
pombast smelt -f          # builds and writes smelt.json
pombast status            # overlays smelt.json, writes status.html
pombast badges            # writes badges.json
pombast team              # writes team.html + team.json
```

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
- **`success/`** — the resolved dependency closures of successful builds, one
  file per component. A component is skipped when any recorded closure still
  pins to the same versions in the BOM under test — that is, when none of *its
  own* dependencies have changed (unless the component, or one of those pins, is
  a SNAPSHOT). Which other components are being smelted has no bearing on the
  key, so excluding or bumping unrelated components never invalidates the cache.

---

## License

[Unlicense](https://unlicense.org/) — public domain.

[javadoc.scijava.org]: https://github.com/scijava/javadoc.scijava.org
