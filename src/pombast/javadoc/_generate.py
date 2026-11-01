"""Generate javadoc from a component's ``-sources`` JAR when no ``-javadoc`` JAR exists.

Some projects (e.g. OME's Bio-Formats) publish sources but not javadoc. For those
we run the ``javadoc`` tool ourselves, as permissively as it allows: doclint off,
source errors ignored, so malformed comments or unresolvable references degrade
the output instead of aborting it. The component's resolved dependency JARs go on
the classpath — without them javadoc cannot attribute signatures at all.

Each dependency whose javadoc is already in the site tree is linked with
``-linkoffline`` against its own exact ``/{g}/{a}/{v}/`` dir (using the
``element-list`` on disk), so links target the versions the component really
depends on — not a BOM union, which would tie this BOM-independent, per-G:A:V
output to whichever BOM generated it first. javadoc treats a host-less URL as
relative to the output dir, so links are generated against a placeholder host
that is then rewritten to the configured URL prefix (or stripped, giving
site-relative links). Anything left unlinked is still a fully qualified name,
which the crosslink phase handles as for published javadoc.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile

from jgo.maven import RepositoryAccessDenied

from pombast.javadoc._fs import atomic_write_text, swap_dir
from pombast.javadoc._unpack import (
    _MARKER,
    UnpackResult,
    UnpackStatus,
    component_javadoc_dir,
)

if TYPE_CHECKING:
    from jgo.maven import MavenContext

    from pombast.core._component import Component

_log = logging.getLogger(__name__)

# The JDK whose javadoc tool renders generated docs. A modern javadoc reads
# older sources fine given ``-source``, and produces the current HTML layout.
GENERATOR_JAVA = 21

# Oldest -source the generator JDK accepts.
_MIN_SOURCE = 8

_TIMEOUT_SECONDS = 1800

# Placeholder host for -linkoffline URLs; rewritten after generation.
_LINK_HOST = "https://pombast.invalid"

# Marks a component dir whose javadoc pombast generated rather than unpacked.
GENERATED_MARKER = ".pombast-generated"

_javadoc_exe: Path | None = None


# A Java source file's package declaration (comments before it are skipped by
# the line anchor; a declaration is always on a line of its own in practice).
_PACKAGE_DECL = re.compile(rb"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)


class GenerateError(Exception):
    """javadoc could not produce output for a component."""


class NothingToDocument(GenerateError):
    """The sources contain no documentable Java (e.g. Kotlin or resources only)."""


def resolve_sources(ctx: MavenContext, comp: Component) -> Path | None:
    """Return the component's ``-sources`` JAR, or None if not published."""
    try:
        return (
            ctx.project(comp.group, comp.name)
            .at_version(comp.version)
            .artifact(classifier="sources", packaging="jar")
            .resolve()
        )
    except RepositoryAccessDenied:
        raise
    except Exception as e:
        _log.debug("No sources artifact for %s (%s)", comp.coordinate, e)
        return None


def generate_component(
    ctx: MavenContext,
    comp: Component,
    site_dir: Path,
    deps: list[Component],
    java_version: int | None,
    *,
    url_prefix: str = "",
) -> UnpackResult:
    """Generate ``comp``'s javadoc from its sources into the site tree.

    Like unpacking, output is staged and swapped into place whole, then marked
    complete, so later runs treat it as cached.
    """
    sources = resolve_sources(ctx, comp)
    if sources is None:
        return UnpackResult(comp, UnpackStatus.MISSING, error="no javadoc or sources")

    javadoc_dir = component_javadoc_dir(site_dir, comp)
    staged = javadoc_dir.with_name(f".{javadoc_dir.name}.staging")
    try:
        if staged.exists():
            shutil.rmtree(staged)
        links = [d for d in deps if _link_index(component_javadoc_dir(site_dir, d))]
        generate_javadoc(
            ctx, comp, sources, staged, deps, java_version, site_dir, links
        )
        _rewrite_link_host(staged, url_prefix.rstrip("/"))
        (staged / GENERATED_MARKER).write_text("")
        (staged / _MARKER).write_text("")
        swap_dir(staged, javadoc_dir)
    except NothingToDocument as e:
        shutil.rmtree(staged, ignore_errors=True)
        _log.info("No javadoc for %s: %s", comp.coordinate, e)
        return UnpackResult(comp, UnpackStatus.MISSING, error=str(e))
    except (GenerateError, OSError) as e:
        shutil.rmtree(staged, ignore_errors=True)
        _log.warning("Failed to generate javadoc for %s: %s", comp.coordinate, e)
        return UnpackResult(comp, UnpackStatus.ERROR, error=str(e))
    return UnpackResult(comp, UnpackStatus.GENERATED, javadoc_dir)


def generate_javadoc(
    ctx: MavenContext,
    comp: Component,
    sources_jar: Path,
    dest: Path,
    deps: list[Component],
    java_version: int | None,
    site_dir: Path | None = None,
    links: list[Component] | None = None,
) -> None:
    """Run javadoc over ``sources_jar``, writing the HTML into ``dest``.

    ``links`` are dependencies with javadoc under ``site_dir`` to link against.

    Raises:
        GenerateError: if javadoc produced no usable output.
    """
    with tempfile.TemporaryDirectory(prefix="pombast-javadoc-") as tmp:
        src = Path(tmp) / "src"
        with ZipFile(sources_jar) as z:
            z.extractall(src)
        # Generate non-modular docs: the union and crosslinker key everything by
        # package, and a module descriptor would demand a full module path.
        for descriptor in src.rglob("module-info.java"):
            descriptor.unlink()
        roots, packages = _source_layout(src)
        if not packages:
            raise NothingToDocument("sources JAR contains no packaged Java sources")

        classpath = _classpath(ctx, deps)
        source = max(_MIN_SOURCE, java_version or _MIN_SOURCE)
        argfile = Path(tmp) / "args"
        lines = [
            "-sourcepath", _quote(os.pathsep.join(str(r) for r in roots)),
            "-classpath", _quote(os.pathsep.join(classpath)),
        ]  # fmt: skip
        for dep in links or []:
            assert site_dir is not None
            lines += [
                "-linkoffline",
                _quote(f"{_LINK_HOST}/{dep.group}/{dep.name}/{dep.version}/"),
                _quote(str(component_javadoc_dir(site_dir, dep))),
            ]
        # Explicit package names rather than -subpackages, which trips a javac
        # AssertionError (Modules.allModules) under -source 8 on JDK 21.
        lines += packages
        argfile.write_text("\n".join(lines) + "\n")

        proc = _run_javadoc(comp, dest, argfile, source, "UTF-8")
        if (
            not (dest / "index.html").is_file()
            and "unmappable character" in proc.stderr
        ):
            # Older projects often have Latin-1 sources; ISO-8859-1 maps every byte.
            shutil.rmtree(dest, ignore_errors=True)
            proc = _run_javadoc(comp, dest, argfile, source, "ISO-8859-1")

    # Ignoring source errors, javadoc may still exit non-zero; what matters is
    # whether it wrote a site.
    if not (dest / "index.html").is_file():
        if "No public or protected classes found" in proc.stderr:
            raise NothingToDocument("no public or protected classes")
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        raise GenerateError(
            f"javadoc exited {proc.returncode} without output: " + " | ".join(tail)
        )
    _log.info(
        "Generated javadoc for %s from sources (javadoc exit %d)",
        comp.coordinate,
        proc.returncode,
    )


def _run_javadoc(
    comp: Component, dest: Path, argfile: Path, source: int, encoding: str
) -> subprocess.CompletedProcess[str]:
    args = [
        str(_javadoc()),
        "-d", str(dest),
        "-source", str(source),
        "-encoding", encoding,
        "-docencoding", "UTF-8",
        "-charset", "UTF-8",
        "-Xdoclint:none",
        "--ignore-source-errors",
        "-quiet",
        "-notimestamp",
        "-Xmaxerrs", "1",
        "-Xmaxwarns", "1",
        "-windowtitle", f"{comp.name} {comp.version} API",
        "-doctitle", f"{comp.name} {comp.version} API",
        "-J-Xmx2g",
        f"@{argfile}",
    ]  # fmt: skip
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise GenerateError(f"javadoc timed out after {_TIMEOUT_SECONDS}s") from e


def _source_layout(src: Path) -> tuple[list[Path], list[str]]:
    """Find the source roots and package names of extracted Java sources.

    Taken from each file's ``package`` declaration rather than the JAR layout,
    since some sources JARs nest the tree under a project dir
    (``jaxen-1.1/src/java/main/org/jaxen/…``). Files whose path disagrees with
    their declared package, and default-package files, are left out.
    """
    roots: set[Path] = set()
    packages: set[str] = set()
    for f in src.rglob("*.java"):
        if "META-INF" in f.parts:
            continue
        try:
            m = _PACKAGE_DECL.search(f.read_bytes()[:65536])
        except OSError:
            continue
        if m is None:
            continue
        pkg = m.group(1).decode("ascii", errors="replace")
        parts = pkg.split(".")
        dir_parts = f.parent.relative_to(src).parts
        if len(dir_parts) < len(parts) or list(dir_parts[-len(parts) :]) != parts:
            continue
        roots.add(f.parents[len(parts)])
        packages.add(pkg)
    return sorted(roots), sorted(packages)


def _link_index(cdir: Path) -> bool:
    """Whether ``cdir`` holds javadoc that -linkoffline can read."""
    return (cdir / "element-list").is_file() or (cdir / "package-list").is_file()


def _rewrite_link_host(javadoc_dir: Path, replacement: str) -> None:
    """Replace the -linkoffline placeholder host with the real URL prefix."""
    for page in javadoc_dir.rglob("*.html"):
        text = page.read_text(encoding="utf-8", errors="surrogateescape")
        if _LINK_HOST in text:
            atomic_write_text(
                page, text.replace(_LINK_HOST, replacement), errors="surrogateescape"
            )


def _classpath(ctx: MavenContext, deps: list[Component]) -> list[str]:
    """Resolve the primary JAR of each dependency; skip any that won't resolve."""
    jars: list[str] = []
    for dep in deps:
        try:
            jar = (
                ctx.project(dep.group, dep.name)
                .at_version(dep.version)
                .artifact()
                .resolve()
            )
        except RepositoryAccessDenied:
            raise
        except Exception as e:
            _log.debug("Classpath: cannot resolve %s (%s)", dep.coordinate, e)
            continue
        if jar is not None and str(jar).endswith(".jar"):
            jars.append(str(jar))
    return jars


def _quote(value: str) -> str:
    """Quote an @argfile value (backslashes and quotes escaped)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _javadoc() -> Path:
    """Locate (downloading if needed) the generator JDK's javadoc executable."""
    global _javadoc_exe
    if _javadoc_exe is None:
        from pombast.maven._builder import locate_java

        home = locate_java(GENERATOR_JAVA)
        exe = home / "bin" / "javadoc" if home is not None else None
        if exe is None or not exe.exists():
            found = shutil.which("javadoc")
            if found is None:
                raise GenerateError(f"No javadoc tool found (Java {GENERATOR_JAVA})")
            exe = Path(found)
        _javadoc_exe = exe
    return _javadoc_exe
