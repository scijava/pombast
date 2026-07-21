"""Tests for javadoc crosslink rewriting."""

from __future__ import annotations

from pombast.core import Component
from pombast.javadoc._crosslink import (
    ClassIndex,
    ClassIndexer,
    crosslink_html,
    resolve_jdk_base,
)
from pombast.javadoc._deps import _java_version, _parse_java_version

_SCIJAVA = Component(group="org.scijava", name="scijava-common", version="2.99.0")
_TF = Component(group="org.tensorflow", name="libtensorflow", version="1.12.0")


def _index() -> ClassIndex:
    return {
        "org.scijava.Context": (_SCIJAVA, "org/scijava/Context.html"),
        "org.tensorflow.Tensor": (_TF, "org/tensorflow/Tensor.html"),
    }


def _crosslink(html: str, index: ClassIndex | None = None, **kw) -> str:
    kw.setdefault("url_prefix", "")
    kw.setdefault("java_version", 8)
    kw.setdefault("jdk_template", "/Java{java}/")
    kw.setdefault("jdk_base_urls", {})
    text, _ = crosslink_html(html, index if index is not None else _index(), **kw)
    return text


class TestResolveJdkBase:
    def test_explicit_map_wins_over_template(self):
        base = resolve_jdk_base(
            8, "/Java{java}/", {"j8": "https://docs.oracle.com/javase/8/docs/api/"}
        )
        assert base == "https://docs.oracle.com/javase/8/docs/api/"

    def test_template_fallback(self):
        assert resolve_jdk_base(11, "/Java{java}/", {}) == "/Java11/"

    def test_none_version(self):
        assert resolve_jdk_base(None, "/Java{java}/", {}) is None

    def test_empty_template_no_map(self):
        assert resolve_jdk_base(8, "", {}) is None


class TestLegacyHrefRewrite:
    def test_flat_prefix_becomes_versioned(self):
        html = '<a href="/SciJava/org/scijava/Context.html">Context</a>'
        out = _crosslink(html)
        assert (
            '<a href="/org.scijava/scijava-common/2.99.0/org/scijava/Context.html">'
            in out
        )

    def test_query_string_preserved(self):
        html = '<a href="/SciJava/org/scijava/Context.html?is-external=true">C</a>'
        out = _crosslink(html)
        assert (
            "/org.scijava/scijava-common/2.99.0/org/scijava/Context.html"
            "?is-external=true" in out
        )

    def test_url_prefix_stripped_and_reapplied(self):
        html = (
            '<a href="https://javadoc.scijava.org/SciJava/org/scijava/'
            'Context.html">C</a>'
        )
        out = _crosslink(html, url_prefix="https://javadoc.scijava.org")
        assert (
            'href="https://javadoc.scijava.org/org.scijava/scijava-common/2.99.0/'
            'org/scijava/Context.html"' in out
        )

    def test_unknown_class_left_untouched(self):
        html = '<a href="/Fiji/net/imglib2/View.html">View</a>'
        assert _crosslink(html) == html

    def test_relative_link_untouched(self):
        html = '<a href="../../../net/imagej/AbstractData.html">AbstractData</a>'
        assert _crosslink(html) == html


class TestJdkLinks:
    def test_default_template_is_noop_when_version_matches(self):
        html = '<a href="/Java8/java/lang/Double.html?is-external=true">Double</a>'
        assert _crosslink(html, java_version=8) == html

    def test_stale_prefix_normalized_to_true_version(self):
        # Baked prefix says Java8, but the component actually targets Java 21.
        html = '<a href="/Java8/java/lang/Double.html">Double</a>'
        out = _crosslink(html, java_version=21)
        assert 'href="/Java21/java/lang/Double.html"' in out

    def test_absolute_oracle_legacy_url_normalized(self):
        html = (
            '<a href="https://docs.oracle.com/javase/8/docs/api/java/lang/'
            'Object.html?is-external=true">Object</a>'
        )
        out = _crosslink(html, java_version=8)
        assert 'href="/Java8/java/lang/Object.html?is-external=true"' in out

    def test_absolute_oracle_modular_url_strips_module(self):
        html = (
            '<a href="https://docs.oracle.com/en/java/javase/11/docs/api/'
            'java.base/java/util/Map.html">Map</a>'
        )
        out = _crosslink(html, java_version=17)
        assert 'href="/Java17/java/util/Map.html"' in out

    def test_proxy_modular_form_strips_module(self):
        html = '<a href="/Java21/java.base/java/lang/String.html">String</a>'
        out = _crosslink(html, java_version=21)
        assert 'href="/Java21/java/lang/String.html"' in out

    def test_java_sun_legacy_url_normalized(self):
        html = (
            '<a href="http://java.sun.com/j2se/1.5.0/docs/api/java/io/'
            'IOException.html">IOException</a>'
        )
        out = _crosslink(html, java_version=8)
        assert 'href="/Java8/java/io/IOException.html"' in out

    def test_explicit_oracle_base(self):
        html = '<a href="/Java8/java/lang/Double.html?is-external=true">Double</a>'
        out = _crosslink(
            html,
            java_version=8,
            jdk_base_urls={"j8": "https://docs.oracle.com/javase/8/docs/api/"},
        )
        assert (
            'href="https://docs.oracle.com/javase/8/docs/api/java/lang/'
            'Double.html?is-external=true"' in out
        )

    def test_site_relative_base_honors_url_prefix(self):
        html = '<a href="https://jd.example/Java8/java/util/Map.html">Map</a>'
        out = _crosslink(html, java_version=11, url_prefix="https://jd.example")
        assert 'href="https://jd.example/Java11/java/util/Map.html"' in out

    def test_unknown_version_leaves_jdk_link_untouched(self):
        html = '<a href="/Java8/java/lang/Double.html">Double</a>'
        assert _crosslink(html, java_version=None) == html

    def test_unseen_host_with_jdk_class_is_normalized(self):
        # No hardcoded base for developer.android.com, but the class is java.*,
        # so shape detection still normalizes it.
        html = (
            '<a href="https://developer.android.com/reference/java/lang/'
            'Object.html">Object</a>'
        )
        out = _crosslink(html, java_version=8)
        assert 'href="/Java8/java/lang/Object.html"' in out

    def test_non_jdk_class_on_same_host_left_untouched(self):
        # android.* is not a JDK package, so it is not touched.
        html = (
            '<a href="https://developer.android.com/reference/android/app/'
            'Activity.html">Activity</a>'
        )
        assert _crosslink(html, java_version=8) == html

    def test_javafx_not_treated_as_jdk(self):
        # javafx.* must not be mistaken for a java.* root.
        html = '<a href="/Java8/javafx/scene/Node.html">Node</a>'
        assert _crosslink(html, java_version=8) == html

    def test_base_path_segment_named_java_not_confused(self):
        # The "java" in ".../en/java/javase/..." is base boilerplate, not the
        # class package; the real package (java.util) must be recovered.
        html = (
            '<a href="https://docs.oracle.com/en/java/javase/17/docs/api/'
            'java.base/java/util/List.html">List</a>'
        )
        out = _crosslink(html, java_version=17)
        assert 'href="/Java17/java/util/List.html"' in out


class TestPlainTextFqcn:
    def test_unlinked_fqcn_is_wrapped(self):
        html = "<code>(org.tensorflow.Tensor&lt;T&gt; image)</code>"
        out = _crosslink(html)
        assert (
            '<a href="/org.tensorflow/libtensorflow/1.12.0/org/tensorflow/'
            'Tensor.html">org.tensorflow.Tensor</a>' in out
        )

    def test_method_fragment_in_href_not_touched(self):
        # The FQCN inside a URL fragment is an attribute value, not body text.
        html = '<a href="Tensors.html#imgByte-org.tensorflow.Tensor-">imgByte</a>'
        assert _crosslink(html) == html

    def test_no_nested_anchor_when_fqcn_is_link_text(self):
        html = '<a href="/SciJava/org/scijava/Context.html">org.scijava.Context</a>'
        out = _crosslink(html)
        # href rewritten, but the anchor text is not re-wrapped.
        assert out.count("<a ") == 1
        assert ">org.scijava.Context</a>" in out
        assert "/org.scijava/scijava-common/2.99.0/" in out

    def test_unknown_fqcn_left_as_text(self):
        html = "<code>com.example.Unknown value</code>"
        assert _crosslink(html) == html


class TestJavaVersion:
    def test_parse_variants(self):
        assert _parse_java_version("1.8") == 8
        assert _parse_java_version("8") == 8
        assert _parse_java_version("11") == 11
        assert _parse_java_version("21") == 21
        assert _parse_java_version("1.6.0") == 6
        assert _parse_java_version("not-a-version") is None

    def test_prefers_release_over_source(self):
        props = {"maven.compiler.source": "8", "maven.compiler.release": "17"}
        assert _java_version(props) == 17

    def test_falls_back_to_scijava_jvm_version(self):
        assert _java_version({"scijava.jvm.version": "21"}) == 21

    def test_none_when_absent(self):
        assert _java_version({}) is None


class TestClassIndexer:
    def _make_javadoc(self, root, comp: Component, pages: list[str]) -> None:
        cdir = root / comp.group / comp.name / comp.version
        for rel in pages:
            path = cdir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def test_class_pages_indexed_scaffolding_skipped(self, tmp_path):
        self._make_javadoc(
            tmp_path,
            _SCIJAVA,
            [
                "org/scijava/Context.html",
                "org/scijava/service/Service.html",
                "org/scijava/Outer.Inner.html",
                "org/scijava/package-summary.html",
                "org/scijava/class-use/Context.html",
                "index.html",
            ],
        )
        index = ClassIndexer(tmp_path).build([_SCIJAVA])
        assert "org.scijava.Context" in index
        assert "org.scijava.service.Service" in index
        assert "org.scijava.Outer.Inner" in index
        assert "org.scijava.package-summary" not in index
        assert "org.scijava.class-use.Context" not in index
        assert "index" not in index

    def test_first_dependency_wins_on_overlap(self, tmp_path):
        other = Component(group="dup", name="other", version="1.0.0")
        self._make_javadoc(tmp_path, _SCIJAVA, ["org/scijava/Context.html"])
        self._make_javadoc(tmp_path, other, ["org/scijava/Context.html"])
        index = ClassIndexer(tmp_path).build([_SCIJAVA, other])
        assert index["org.scijava.Context"][0] == _SCIJAVA
