"""Tests for javadoc crosslink rewriting."""

from __future__ import annotations

from pombast.core import Component
from pombast.javadoc._crosslink import (
    ClassIndex,
    ClassIndexer,
    JdkModuleResolver,
    _parse_module_list,
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


def _crosslink(
    html: str,
    index: ClassIndex | None = None,
    *,
    url_prefix: str = "",
    java_version: int | None = 8,
    jdk_template: str = "/Java{java}/",
    jdk_base_urls: dict[str, str] | None = None,
    jdk_modules: dict[str, str] | None = None,
) -> str:
    base = resolve_jdk_base(java_version, jdk_template, jdk_base_urls or {})
    text, _ = crosslink_html(
        html,
        index if index is not None else _index(),
        url_prefix=url_prefix,
        jdk_base=base,
        jdk_modules=jdk_modules or {},
    )
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


class TestJdkModuleQualification:
    _MODULES = {"java.lang": "java.base", "javax.swing": "java.desktop"}

    def test_module_prefixed_for_java9plus(self):
        html = '<a href="/Java8/java/lang/String.html">String</a>'
        out = _crosslink(html, java_version=21, jdk_modules=self._MODULES)
        assert 'href="/Java21/java.base/java/lang/String.html"' in out

    def test_module_from_correct_package(self):
        html = '<a href="/Java8/javax/swing/JPanel.html">JPanel</a>'
        out = _crosslink(html, java_version=21, jdk_modules=self._MODULES)
        assert 'href="/Java21/java.desktop/javax/swing/JPanel.html"' in out

    def test_no_module_when_package_absent(self):
        # Empty module map (e.g. Java 8) ⇒ module-less.
        html = '<a href="/Java8/java/lang/String.html">String</a>'
        out = _crosslink(html, java_version=8, jdk_modules={})
        assert 'href="/Java8/java/lang/String.html"' in out

    def test_absolute_modular_source_requalified(self):
        html = (
            '<a href="https://docs.oracle.com/en/java/javase/11/docs/api/'
            'java.base/java/util/Map.html">Map</a>'
        )
        out = _crosslink(html, java_version=17, jdk_modules={"java.util": "java.base"})
        assert 'href="/Java17/java.base/java/util/Map.html"' in out


class TestParseModuleList:
    def test_modular_element_list(self):
        text = (
            "module:java.base\njava.io\njava.lang\nmodule:java.desktop\njavax.swing\n"
        )
        assert _parse_module_list(text) == {
            "java.io": "java.base",
            "java.lang": "java.base",
            "javax.swing": "java.desktop",
        }

    def test_flat_package_list_has_no_modules(self):
        assert _parse_module_list("java.applet\njava.awt\njava.awt.color\n") == {}


class TestJdkModuleResolver:
    def test_fetches_and_caches(self):
        calls: list[str] = []

        def opener(url: str) -> str:
            calls.append(url)
            return "module:java.base\njava.lang\n"

        r = JdkModuleResolver(url_prefix="https://javadoc.scijava.org", opener=opener)
        assert r.modules("/Java21/") == {"java.lang": "java.base"}
        assert r.modules("/Java21/") == {"java.lang": "java.base"}  # cached
        assert calls == ["https://javadoc.scijava.org/Java21/element-list"]

    def test_falls_back_to_package_list(self):
        def opener(url: str) -> str:
            if url.endswith("element-list"):
                raise OSError("404")
            return "java.applet\njava.awt\n"

        r = JdkModuleResolver(opener=opener)
        assert r.modules("https://docs.oracle.com/javase/8/docs/api/") == {}

    def test_site_relative_base_without_prefix_is_module_less(self):
        def opener(url: str) -> str:  # pragma: no cover - must not be called
            raise AssertionError("should not fetch without a host")

        r = JdkModuleResolver(url_prefix="", opener=opener)
        assert r.modules("/Java21/") == {}

    def test_fetch_failure_degrades_to_empty(self):
        def opener(url: str) -> str:
            raise OSError("network down")

        r = JdkModuleResolver(opener=opener)
        assert r.modules("https://docs.oracle.com/en/java/javase/21/docs/api/") == {}


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

    def test_modular_javadoc_strips_module_from_fqcn(self, tmp_path):
        # ImageJ's module is "ij", so Java 9+ javadoc doubles the leading segment.
        ij = Component(group="net.imagej", name="ij", version="1.53r")
        cdir = tmp_path / ij.group / ij.name / ij.version
        (cdir / "ij" / "ij" / "plugin").mkdir(parents=True)
        (cdir / "ij" / "ij" / "plugin" / "PlugIn.html").write_text("")
        (cdir / "ij" / "ij" / "ImagePlus.html").write_text("")
        (cdir / "element-list").write_text("module:ij\nij\nij.plugin\n")
        index = ClassIndexer(tmp_path).build([ij])
        # Key is the real FQCN; value is the actual (module-doubled) on-disk path.
        assert index["ij.plugin.PlugIn"] == (ij, "ij/ij/plugin/PlugIn.html")
        assert index["ij.ImagePlus"] == (ij, "ij/ij/ImagePlus.html")
        assert "ij.ij.plugin.PlugIn" not in index


class TestModularDepLinks:
    _IJ = Component(group="net.imagej", name="ij", version="1.53r")
    # Modular index: real FQCN -> module-doubled on-disk path.
    _INDEX: ClassIndex = {"ij.plugin.PlugIn": (_IJ, "ij/ij/plugin/PlugIn.html")}

    def test_doubled_legacy_href_resolves_via_suffix_search(self):
        html = '<a href="/ImageJ1/ij/ij/plugin/PlugIn.html">PlugIn</a>'
        out = _crosslink(html, self._INDEX)
        assert 'href="/net.imagej/ij/1.53r/ij/ij/plugin/PlugIn.html"' in out

    def test_nonmodular_legacy_href_maps_to_modular_ondisk_path(self):
        # Source link had no module doubling, but the resolved version is modular;
        # the link must land on the real (doubled) on-disk file.
        html = '<a href="/ImageJ1/ij/plugin/PlugIn.html">PlugIn</a>'
        out = _crosslink(html, self._INDEX)
        assert 'href="/net.imagej/ij/1.53r/ij/ij/plugin/PlugIn.html"' in out

    def test_plaintext_real_fqcn_is_linked(self):
        html = "<code>(ij.plugin.PlugIn p)</code>"
        out = _crosslink(html, self._INDEX)
        assert (
            '<a href="/net.imagej/ij/1.53r/ij/ij/plugin/PlugIn.html">'
            "ij.plugin.PlugIn</a>" in out
        )
