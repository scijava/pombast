"""Rewrite a component's javadoc HTML so class references resolve to the exact
versioned javadoc of that component's dependencies.

Old SciJava-built javadoc baked *irreproducible* links: cross-artifact class
references point at flat, deployment-specific prefixes (``/SciJava/…``,
``/ImgLib2/…``, ``/Java8/…``) rather than the versioned ``/{g}/{a}/{v}/…`` layout
this site uses, and some referenced classes were never linked at all (their
fully-qualified name is embedded as plain text because no ``-link`` target was
supplied at build time).

This step repairs both, driven entirely by the component's *own* resolved
dependency set (as reported by jgo) — never by the BOM's managed versions. It is
therefore a pure function of the component's G:A:V, cacheable independently of
the unpack step via its own marker (:data:`_CROSSLINK_MARKER`).

Three rewrites, applied in a single tag-aware pass so attributes and existing
anchors are never corrupted:

* **Legacy flat-prefix hrefs** — ``href="/SciJava/org/scijava/Context.html"`` →
  ``/{g}/{a}/{v}/org/scijava/Context.html`` for the dependency that actually owns
  ``org.scijava.Context``.
* **Unlinked plain-text FQCNs** — ``org.tensorflow.Tensor`` appearing as signature
  text is wrapped in an anchor pointing at the owning dependency.
* **JDK links** — a link is a JDK link when its *class* is a JDK class
  (``java.*``, ``javax.*``, …), detected by the shape of the URL path rather than
  a list of known hosts, so every baked-in form (absolute Oracle/sun URLs across
  eras, modular ``.../java.base/…`` paths, the SciJava ``/Java{N}/`` proxy, even
  unseen ones) is handled the same way. Such links are normalized onto a configured
  API base (see :func:`resolve_jdk_base`) at the component's *true* target Java
  version as reported by jgo — not the often-stale version baked into the link.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from pombast.javadoc._unpack import TOPLEVEL_HTML_DOCS, component_javadoc_dir

if TYPE_CHECKING:
    from pathlib import Path

    from pombast.core._component import Component

_log = logging.getLogger(__name__)

# Marker written into a component's javadoc dir once its HTML has been
# crosslinked. Independent of the unpack marker so crosslinking can be re-run
# (e.g. after improving the algorithm) without re-extracting.
_CROSSLINK_MARKER = ".pombast-crosslinked"

# Package roots whose classes live in the JDK itself (no Maven artifact to link
# to). A link whose class *package* starts with one of these is a JDK link,
# regardless of what host/prefix the original javadoc pointed it at.
_JDK_ROOT_PREFIXES = (
    "java",
    "javax",
    "jdk",
    "org.w3c",
    "org.xml",
    "org.omg",
    "org.ietf",
)

# Splits HTML into tags; the text between matches is content we may link into.
_TAG_RE = re.compile(r"<[^>]+>")

# An <a ...> opening tag (not <abbr>, <article>, …) and its </a> counterpart.
_A_OPEN_RE = re.compile(r"<a[\s>]", re.IGNORECASE)
_A_CLOSE_RE = re.compile(r"</a\s*>", re.IGNORECASE)

# The href value of an anchor tag.
_HREF_RE = re.compile(r'href="([^"]*)"', re.IGNORECASE)

# An absolute site path to a class page: /{seg0}/{class/path}.html[?#...].
# seg0 is the (ignored) legacy flat prefix; the remainder is the class path.
_ABS_CLASS_RE = re.compile(r"^/([^/]+)/(.+?\.html)([?#].*)?$")

# A dotted identifier chain in body text — a candidate fully-qualified class name.
_FQCN_CANDIDATE_RE = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+")

# A single package-path segment (lowercase Java package component).
_PKG_SEG_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# A class-page filename, allowing nested classes (``Map.Entry.html``).
_CLASS_FILE_RE = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\.html$")


class CrosslinkStatus(Enum):
    """Outcome of crosslinking one component's javadoc."""

    CROSSLINKED = "crosslinked"  # HTML rewritten (or confirmed clean) this run
    CACHED = "cached"  # marker present, skipped
    SKIPPED = "skipped"  # nothing to do (no javadoc dir)
    ERROR = "error"  # rewrite failed


@dataclass
class CrosslinkResult:
    """Result of crosslinking a single component's javadoc."""

    component: Component
    status: CrosslinkStatus
    files_changed: int = 0
    links_rewritten: int = 0
    error: str | None = None


# Target of a class link: the owning dependency plus the page's path within it.
ClassIndex = dict[str, "tuple[Component, str]"]


def resolve_jdk_base(
    version: int | None,
    template: str,
    base_urls: dict[str, str],
) -> str | None:
    """Resolve the API base URL for JDK ``java.*`` links at ``version``.

    An explicit ``base_urls`` entry (keyed ``j8``, ``j21``, …) wins — needed
    because Oracle changes its URL structure between releases. Otherwise
    ``template`` is formatted with ``{java}`` (e.g. the default ``/Java{java}/``,
    which reproduces SciJava's proxied ``/Java8/`` prefixes). Returns ``None``
    when neither yields a base, meaning "leave the link untouched".

    NOTE: modular Oracle URLs (Java 9+) embed a module segment
    (``…/api/java.base/java/lang/String.html``) that this does not synthesize;
    the flat ``java/lang/String.html`` path is appended as-is. Fine for the
    proxied ``/Java{N}/`` case; explicit Oracle bases for Java 9+ are a known gap.
    """
    if version is None:
        return None
    key = f"j{version}"
    if key in base_urls:
        return base_urls[key]
    if template:
        try:
            return template.format(java=version)
        except (KeyError, IndexError):
            _log.warning("Malformed jdk_api_url_template: %r", template)
    return None


class ClassIndexer:
    """Builds and memoizes per-dependency FQCN → page maps.

    One instance is shared across a run so a dependency's class listing is
    scanned from disk at most once, even though many components share it.
    """

    def __init__(self, site_dir: Path):
        self._site_dir = site_dir
        self._cache: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def _pages(self, comp: Component) -> dict[str, str]:
        """Return ``{fqcn: relpath}`` for one dependency's unpacked javadoc."""
        cdir = component_javadoc_dir(self._site_dir, comp)
        key = str(cdir)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        pages = dict(_iter_class_pages(cdir)) if cdir.is_dir() else {}
        with self._lock:
            self._cache[key] = pages
        return pages

    def build(self, deps: list[Component]) -> ClassIndex:
        """Assemble a first-wins FQCN → (dependency, relpath) index.

        Overlapping classes across dependencies resolve to the first dependency
        in ``deps`` that provides them, matching the "first one wins" policy for
        the rare split-package case.
        """
        index: ClassIndex = {}
        for dep in deps:
            for fqcn, rel in self._pages(dep).items():
                index.setdefault(fqcn, (dep, rel))
        return index


def _iter_class_pages(cdir: Path):
    """Yield ``(fqcn, relpath)`` for each class page under a javadoc dir.

    Skips package/overview/index/use scaffolding — only true per-class pages
    (including nested ``Outer.Inner.html``) contribute linkable targets.
    """
    for html in cdir.rglob("*.html"):
        if not html.is_file():
            continue
        name = html.name
        if name in TOPLEVEL_HTML_DOCS or name.startswith("package-"):
            continue
        parts = html.relative_to(cdir).parts
        if "class-use" in parts or "doc-files" in parts:
            continue
        rel = html.relative_to(cdir).as_posix()
        fqcn = rel[:-5].replace("/", ".")  # strip ".html"
        yield fqcn, rel


def _jdk_class_path(href: str) -> tuple[str, str] | None:
    """If ``href`` targets a JDK class, return ``(class_path, query)``, else ``None``.

    Recognized by *shape*, not by a list of known hosts: the class path is the
    suffix of the URL path whose segments form a package rooted at a JDK API
    package (``java.*``, ``javax.*``, …) down to a ``Class.html`` file. Everything
    to its left — scheme, host, ``/docs/api/`` boilerplate, a ``/Java{N}/`` proxy
    prefix, a JPMS module segment (``java.base``) — is simply skipped, so any
    prefix form (including ones we have never seen) is handled uniformly and the
    result is normalized to the non-modular ``java/lang/Object.html`` form.
    """
    body = href
    scheme = body.find("://")
    if scheme != -1:
        slash = body.find("/", scheme + 3)
        body = body[slash:] if slash != -1 else ""

    cut = min((i for i in (body.find("?"), body.find("#")) if i != -1), default=-1)
    path, query = (body[:cut], body[cut:]) if cut != -1 else (body, "")

    segments = [s for s in path.split("/") if s]
    if len(segments) < 2 or not _CLASS_FILE_RE.match(segments[-1]):
        return None

    # Leftmost start whose suffix is a valid package path rooted at the JDK. Base
    # boilerplate (``docs``, ``api``, ``11``) and module segments fail the package
    # check, so the scan lands on the true top-level package.
    for i in range(len(segments) - 1):
        pkg_segs = segments[i:-1]
        if not all(_PKG_SEG_RE.match(s) for s in pkg_segs):
            continue
        package = ".".join(pkg_segs)
        if any(package == r or package.startswith(f"{r}.") for r in _JDK_ROOT_PREFIXES):
            return "/".join(segments[i:]), query
    return None


def _rewrite_href(
    href: str,
    index: ClassIndex,
    *,
    url_prefix: str,
    java_version: int | None,
    jdk_template: str,
    jdk_base_urls: dict[str, str],
) -> str | None:
    """Return a repaired href, or ``None`` to leave it unchanged.

    A dependency link is an absolute *site* path (``/{prefix}/{class}.html``, the
    irreproducible legacy form) whose class is owned by a resolved dependency. A
    JDK link is recognized by shape in any prefix form (see :func:`_jdk_class_path`).
    Component-internal relative links (``../../…``) are already valid and left alone.
    """
    rel = href
    if url_prefix and href.startswith(url_prefix):
        rel = href[len(url_prefix) :]

    if rel.startswith("/"):
        m = _ABS_CLASS_RE.match(rel)
        if m:
            class_path, query = m.group(2), m.group(3) or ""
            owner = index.get(class_path[:-5].replace("/", "."))
            if owner is not None:
                dep, relpath = owner
                return f"{url_prefix}/{dep.group}/{dep.name}/{dep.version}/{relpath}{query}"

    jdk = _jdk_class_path(href)
    if jdk is not None:
        class_path, query = jdk
        base = resolve_jdk_base(java_version, jdk_template, jdk_base_urls)
        if base is not None:
            # A site-relative base (e.g. the default "/Java21/") is anchored to the
            # deployed root, so it carries url_prefix like a dependency link would;
            # an absolute base (Oracle URL) is used verbatim.
            prefix = url_prefix if base.startswith("/") else ""
            return f"{prefix}{base.rstrip('/')}/{class_path}{query}"
    return None


def _rewrite_a_tag(tag: str, **kw) -> tuple[str, int]:
    """Rewrite the href of one ``<a>`` tag; return (tag, links_rewritten)."""
    m = _HREF_RE.search(tag)
    if not m:
        return tag, 0
    new_href = _rewrite_href(m.group(1), **kw)
    if new_href is None or new_href == m.group(1):
        return tag, 0
    return tag[: m.start(1)] + new_href + tag[m.end(1) :], 1


def _link_text_fqcns(
    text: str, index: ClassIndex, *, url_prefix: str
) -> tuple[str, int]:
    """Wrap known plain-text FQCNs in ``text`` with anchors; return (text, n)."""
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        fqcn = m.group(0)
        owner = index.get(fqcn)
        if owner is None:
            return fqcn
        dep, relpath = owner
        count += 1
        href = f"{url_prefix}/{dep.group}/{dep.name}/{dep.version}/{relpath}"
        return f'<a href="{href}">{fqcn}</a>'

    return _FQCN_CANDIDATE_RE.sub(repl, text), count


def crosslink_html(
    text: str,
    index: ClassIndex,
    *,
    url_prefix: str,
    java_version: int | None = None,
    jdk_template: str,
    jdk_base_urls: dict[str, str],
) -> tuple[str, int]:
    """Apply all three rewrites to one HTML document; return (html, n_rewrites).

    A single left-to-right pass over tags and the text between them: hrefs are
    repaired on ``<a>`` tags, and bare FQCNs are linked only in body text that is
    not already inside an anchor (avoiding nested/invalid ``<a>`` elements).
    """
    href_kw = dict(
        url_prefix=url_prefix,
        java_version=java_version,
        jdk_template=jdk_template,
        jdk_base_urls=jdk_base_urls,
    )
    out: list[str] = []
    pos = 0
    anchor_depth = 0
    total = 0

    for m in _TAG_RE.finditer(text):
        seg = text[pos : m.start()]
        if seg:
            if anchor_depth > 0:
                out.append(seg)
            else:
                linked, n = _link_text_fqcns(seg, index, url_prefix=url_prefix)
                out.append(linked)
                total += n
        tag = m.group()
        if _A_OPEN_RE.match(tag):
            tag, n = _rewrite_a_tag(tag, index=index, **href_kw)
            total += n
            anchor_depth += 1
        elif _A_CLOSE_RE.match(tag):
            anchor_depth = max(0, anchor_depth - 1)
        out.append(tag)
        pos = m.end()

    tail = text[pos:]
    if tail:
        if anchor_depth > 0:
            out.append(tail)
        else:
            linked, n = _link_text_fqcns(tail, index, url_prefix=url_prefix)
            out.append(linked)
            total += n

    return "".join(out), total


def crosslink_component(
    site_dir: Path,
    comp: Component,
    deps: list[Component],
    indexer: ClassIndexer,
    *,
    url_prefix: str = "",
    java_version: int | None = None,
    jdk_template: str = "/Java{java}/",
    jdk_base_urls: dict[str, str] | None = None,
    force: bool = False,
) -> CrosslinkResult:
    """Crosslink one component's unpacked javadoc against its dependency closure.

    Args:
        site_dir: Root of the javadoc site tree.
        comp: The component whose HTML to rewrite.
        deps: The component's resolved dependencies (from jgo), whose unpacked
            javadoc supplies the FQCN → page index. Order sets first-wins.
        indexer: Shared class indexer (memoizes per-dependency scans).
        url_prefix: Absolute prefix for rewritten links; empty ⇒ site-relative.
        java_version: The component's target Java version (from jgo), used to pick
            the JDK API base; ``None`` leaves JDK links untouched.
        jdk_template: ``{java}``-templated base for JDK links.
        jdk_base_urls: Explicit per-version JDK API bases (``j8`` → URL).
        force: Re-crosslink even if the marker is present.
    """
    javadoc_dir = component_javadoc_dir(site_dir, comp)
    marker = javadoc_dir / _CROSSLINK_MARKER
    base_urls = jdk_base_urls or {}

    if not javadoc_dir.is_dir():
        return CrosslinkResult(comp, CrosslinkStatus.SKIPPED)
    if marker.exists() and not force:
        return CrosslinkResult(comp, CrosslinkStatus.CACHED)

    index = indexer.build(deps)

    files_changed = 0
    links = 0
    try:
        for html in javadoc_dir.rglob("*.html"):
            if not html.is_file():
                continue
            text = html.read_text(encoding="utf-8", errors="surrogateescape")
            new_text, n = crosslink_html(
                text,
                index,
                url_prefix=url_prefix,
                java_version=java_version,
                jdk_template=jdk_template,
                jdk_base_urls=base_urls,
            )
            if n:
                html.write_text(new_text, encoding="utf-8", errors="surrogateescape")
                files_changed += 1
                links += n
    except OSError as e:
        _log.warning("Failed to crosslink %s: %s", comp.coordinate, e)
        return CrosslinkResult(comp, CrosslinkStatus.ERROR, error=str(e))

    marker.write_text("")
    _log.info(
        "Crosslinked %s: %d links across %d files",
        comp.coordinate,
        links,
        files_changed,
    )
    return CrosslinkResult(comp, CrosslinkStatus.CROSSLINKED, files_changed, links)
