"""Tests for the javadoc union, site-wide maps, and hard-link-safe writes."""

from __future__ import annotations

import os

from pombast.core import Component
from pombast.javadoc._fs import atomic_write_text, swap_dir
from pombast.javadoc._site import build_site_maps
from pombast.javadoc._union import build_union
from pombast.javadoc._unpack import _MARKER

_BOM = "org.scijava/pom-scijava"


def _comp(coord: str) -> Component:
    g, a, v = coord.split(":")
    return Component(group=g, name=a, version=v)


def _javadoc(site, coord: str, pages: list[str], element_list: str) -> Component:
    """Fake an unpacked component: marker, element-list, and empty class pages."""
    comp = _comp(coord)
    cdir = site / comp.group / comp.name / comp.version
    cdir.mkdir(parents=True)
    (cdir / _MARKER).write_text("")
    (cdir / "element-list").write_text(element_list)
    for page in pages:
        (cdir / page).parent.mkdir(parents=True, exist_ok=True)
        (cdir / page).write_text("<html></html>")
    return comp


def _flat(site, coord="org.scijava:scijava-common:2.99.0") -> Component:
    return _javadoc(
        site,
        coord,
        [
            "index.html",
            "allclasses-index.html",
            "package-summary.html",  # top-level: not redirected
            "index-files/index-1.html",
            "org/scijava/Context.html",
            "org/scijava/package-summary.html",
        ],
        "org.scijava\n",
    )


def _modular(site, coord="net.imagej:ij:1.54p") -> Component:
    return _javadoc(
        site,
        coord,
        [
            "index.html",
            "ij/module-summary.html",
            "ij/ij/ImagePlus.html",
            "ij/ij/package-summary.html",
        ],
        "module:ij\nij\n",
    )


def _tsv(site, version: str) -> dict[str, str]:
    rows = (site / _BOM / version / "redirects.tsv").read_text().splitlines()
    return dict(r.split("\t") for r in rows)


class TestUnion:
    def test_flat_component(self, tmp_path):
        comp = _flat(tmp_path)
        build_union(tmp_path, _comp("org.scijava:pom-scijava:45.1.0"), [comp])
        assert _tsv(tmp_path, "45.1.0") == {
            "/org.scijava/pom-scijava/45.1.0/org/scijava/Context.html": "/org.scijava/scijava-common/2.99.0/org/scijava/Context.html",
            "/org.scijava/pom-scijava/45.1.0/org/scijava/package-summary.html": "/org.scijava/scijava-common/2.99.0/org/scijava/package-summary.html",
        }

    def test_modular_component_keyed_by_class_path(self, tmp_path):
        comp = _modular(tmp_path)
        build_union(tmp_path, _comp("org.scijava:pom-scijava:45.1.0"), [comp])
        # The union's element-list is flat, so -link consumers request ij/…;
        # the redirect target keeps the real module-nested location.
        assert _tsv(tmp_path, "45.1.0") == {
            "/org.scijava/pom-scijava/45.1.0/ij/ImagePlus.html": "/net.imagej/ij/1.54p/ij/ij/ImagePlus.html",
            "/org.scijava/pom-scijava/45.1.0/ij/package-summary.html": "/net.imagej/ij/1.54p/ij/ij/package-summary.html",
        }
        elements = (tmp_path / _BOM / "45.1.0" / "element-list").read_text()
        assert elements == "ij\n"

    def test_shared_path_goes_to_first_component(self, tmp_path):
        a = _flat(tmp_path, "org.scijava:scijava-common:2.99.0")
        b = _flat(tmp_path, "org.scijava:scijava-other:1.0.0")
        build_union(tmp_path, _comp("org.scijava:pom-scijava:45.1.0"), [b, a])
        target = _tsv(tmp_path, "45.1.0")[
            "/org.scijava/pom-scijava/45.1.0/org/scijava/package-summary.html"
        ]
        assert target.startswith("/org.scijava/scijava-other/")

    def test_landing_page_and_no_stale_maps(self, tmp_path):
        comp = _flat(tmp_path)
        out = tmp_path / _BOM / "45.1.0"
        out.mkdir(parents=True)
        (out / "redirects.map").write_text("stale")
        (out / "redirects.conf").write_text("stale")
        build_union(tmp_path, _comp("org.scijava:pom-scijava:45.1.0"), [comp])
        landing = (out / "index.html").read_text()
        assert 'href="../../../org.scijava/scijava-common/2.99.0/"' in landing
        assert not (out / "redirects.map").exists()
        assert not (out / "redirects.conf").exists()


class TestSiteMaps:
    def _build(self, site):
        common_old = _flat(site, "org.scijava:scijava-common:2.98.0")
        (
            site / "org.scijava/scijava-common/2.98.0/org/scijava/Removed.html"
        ).write_text("")
        common_new = _flat(site, "org.scijava:scijava-common:2.99.0")
        build_union(site, _comp("org.scijava:pom-scijava:44.0.0"), [common_old])
        build_union(site, _comp("org.scijava:pom-scijava:45.0.0"), [common_new])
        build_union(
            site, _comp("org.scijava:pom-scijava:45.1.1-SNAPSHOT"), [common_new]
        )
        return build_site_maps(site)

    def _map(self, path) -> dict[str, str]:
        return dict(line.split(" ") for line in path.read_text().splitlines())

    def test_latest_excludes_snapshots(self, tmp_path):
        self._build(tmp_path)
        assert self._map(tmp_path / "latest.map") == {
            "org.scijava/pom-scijava": "45.0.0",
            "org.scijava/scijava-common": "2.99.0",
        }

    def test_redirects_span_all_unions(self, tmp_path):
        result = self._build(tmp_path)
        redirects = self._map(tmp_path / "redirects.map")
        assert result.redirect_count == len(redirects) == 7
        assert (
            redirects["/org.scijava/pom-scijava/44.0.0/org/scijava/Removed.html"]
            == "/org.scijava/scijava-common/2.98.0/org/scijava/Removed.html"
        )

    def test_fallback_covers_only_removed_paths(self, tmp_path):
        self._build(tmp_path)
        assert self._map(tmp_path / "latest-fallback.map") == {
            "/org.scijava/pom-scijava/latest/org/scijava/Removed.html": "/org.scijava/pom-scijava/44.0.0/org/scijava/Removed.html",
        }

    def test_ignores_hidden_staging_dirs(self, tmp_path):
        _flat(tmp_path, "org.scijava:scijava-common:2.99.0")
        staging = tmp_path / "org.scijava/scijava-common/.3.0.0.staging"
        staging.mkdir()
        (staging / _MARKER).write_text("")
        build_site_maps(tmp_path)
        assert self._map(tmp_path / "latest.map") == {
            "org.scijava/scijava-common": "2.99.0",
        }


class TestHardLinkSafety:
    """Published files are hard links into the build tree; never edit in place."""

    def test_atomic_write_leaves_hard_link_untouched(self, tmp_path):
        built = tmp_path / "built.html"
        built.write_text("old")
        published = tmp_path / "published.html"
        os.link(built, published)
        atomic_write_text(built, "new")
        assert built.read_text() == "new"
        assert published.read_text() == "old"

    def test_swap_dir_leaves_hard_link_untouched(self, tmp_path):
        dest = tmp_path / "1.0.0"
        dest.mkdir()
        (dest / "A.html").write_text("old")
        published = tmp_path / "published.html"
        os.link(dest / "A.html", published)
        staged = tmp_path / ".1.0.0.staging"
        staged.mkdir()
        (staged / "A.html").write_text("new")
        swap_dir(staged, dest)
        assert (dest / "A.html").read_text() == "new"
        assert published.read_text() == "old"
        assert not staged.exists()
        assert not (tmp_path / ".1.0.0.old").exists()


class TestGenerate:
    def test_link_host_rewritten_site_relative(self, tmp_path):
        from pombast.javadoc._generate import _LINK_HOST, _rewrite_link_host

        page = tmp_path / "loci/formats/ImageReader.html"
        page.parent.mkdir(parents=True)
        page.write_text(f'<a href="{_LINK_HOST}/g/a/1.0/x/Y.html">Y</a>')
        _rewrite_link_host(tmp_path, "")
        assert page.read_text() == '<a href="/g/a/1.0/x/Y.html">Y</a>'

    def test_link_host_rewritten_with_prefix(self, tmp_path):
        from pombast.javadoc._generate import _LINK_HOST, _rewrite_link_host

        page = tmp_path / "A.html"
        page.write_text(f'<a href="{_LINK_HOST}/g/a/1.0/">a</a>')
        _rewrite_link_host(tmp_path, "https://javadoc.scijava.org")
        assert 'href="https://javadoc.scijava.org/g/a/1.0/"' in page.read_text()

    def test_source_layout_from_package_declarations(self, tmp_path):
        from pombast.javadoc._generate import _source_layout

        nested = tmp_path / "jaxen-1.1/src/java/main/org/jaxen"
        nested.mkdir(parents=True)
        (nested / "XPath.java").write_text("/* c */\npackage org.jaxen;\nclass X {}")
        (tmp_path / "Default.java").write_text("class D {}")
        stray = tmp_path / "misplaced"
        stray.mkdir()
        (stray / "Y.java").write_text("package org.other;")
        roots, packages = _source_layout(tmp_path)
        assert roots == [tmp_path / "jaxen-1.1/src/java/main"]
        assert packages == ["org.jaxen"]


def _duplicate_central_directory(jar) -> None:
    """Rewrite ``jar`` so its central directory lists every entry twice."""
    import struct

    data = jar.read_bytes()
    eocd = data.rindex(b"PK\x05\x06")
    (_, _, _, _, count, cd_size, cd_offset, _) = struct.unpack(
        "<4sHHHHIIH", data[eocd : eocd + 22]
    )
    cd = data[cd_offset : cd_offset + cd_size]
    tail = struct.pack(
        "<4sHHHHIIH", b"PK\x05\x06", 0, 0, 2 * count, 2 * count, 2 * cd_size,
        cd_offset, 0,
    )  # fmt: skip
    jar.write_bytes(data[:cd_offset] + cd + cd + tail)


class TestUnpack:
    def test_extracts_jar_with_duplicated_central_directory(self, tmp_path):
        from zipfile import ZipFile

        from pombast.javadoc._unpack import _extract

        jar = tmp_path / "asm-javadoc.jar"
        with ZipFile(jar, "w") as z:
            z.writestr("index.html", "<html>index</html>")
            z.writestr("org/objectweb/asm/ClassVisitor.html", "<html>cv</html>")
        _duplicate_central_directory(jar)
        with ZipFile(jar) as z:
            assert len(z.infolist()) == 4  # as in ASM 5.0.x javadoc JARs

        dest = tmp_path / "out"
        _extract(jar, dest)
        assert (dest / "index.html").read_text() == "<html>index</html>"
        assert (
            dest / "org/objectweb/asm/ClassVisitor.html"
        ).read_text() == "<html>cv</html>"


class TestSnapshotRounding:
    def _ctx(self, tmp_path, monkeypatch, versions):
        from jgo.maven import MavenContext

        from pombast.javadoc import _deps

        monkeypatch.setattr(_deps, "_rounded", {})

        def no_network(*args, **kwargs):
            raise AssertionError("unexpected HTTP request")

        monkeypatch.setattr("jgo.util.http.request", no_network)
        meta = tmp_path / "sc/fiji/spim_data/maven-metadata-central.xml"
        meta.parent.mkdir(parents=True)
        listed = "".join(f"<version>{v}</version>" for v in versions)
        meta.write_text(
            "<metadata><groupId>sc.fiji</groupId><artifactId>spim_data</artifactId>"
            f"<versioning><versions>{listed}</versions></versioning></metadata>"
        )
        # Fresh cached metadata: update(max_age=...) makes no request.
        return MavenContext(
            repo_cache=tmp_path, local_repos=[], remote_repos={"central": "x"}
        )

    def _round(self, ctx, version):
        from pombast.javadoc._deps import _round_snapshot

        return _round_snapshot(ctx, "sc.fiji", "spim_data", version)

    def test_rounds_to_the_release_it_led_up_to(self, tmp_path, monkeypatch):
        ctx = self._ctx(tmp_path, monkeypatch, ["0.2.0", "0.2.1", "0.3.0"])
        assert self._round(ctx, "0.2.1-SNAPSHOT") == "0.2.1"

    def test_else_newest_older_release(self, tmp_path, monkeypatch):
        ctx = self._ctx(tmp_path, monkeypatch, ["0.1.9", "0.2.0", "0.3.0"])
        assert self._round(ctx, "0.2.1-SNAPSHOT") == "0.2.0"

    def test_else_oldest_newer_release(self, tmp_path, monkeypatch):
        ctx = self._ctx(tmp_path, monkeypatch, ["1.0.0", "0.4.0", "0.5.0-SNAPSHOT"])
        assert self._round(ctx, "0.2.1-SNAPSHOT") == "0.4.0"

    def test_no_releases_drops_it(self, tmp_path, monkeypatch):
        ctx = self._ctx(tmp_path, monkeypatch, ["0.2.1-SNAPSHOT"])
        assert self._round(ctx, "0.2.1-SNAPSHOT") is None


class TestEmptyStubs:
    def test_stub_jar_is_detected(self, tmp_path):
        from zipfile import ZipFile

        from pombast.javadoc._unpack import _has_html

        stub = tmp_path / "stub-javadoc.jar"
        with ZipFile(stub, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        real = tmp_path / "real-javadoc.jar"
        with ZipFile(real, "w") as z:
            z.writestr("docs/api/index.html", "<html></html>")
        assert not _has_html(stub)
        assert _has_html(real)

    def test_pages_found_in_subdir(self, tmp_path):
        from pombast.javadoc._unpack import has_pages

        (tmp_path / "META-INF").mkdir()
        assert not has_pages(tmp_path)
        (tmp_path / "apidocs").mkdir()
        (tmp_path / "apidocs/index.html").write_text("")
        assert has_pages(tmp_path)

    def test_latest_skips_versions_without_pages(self, tmp_path):
        _flat(tmp_path, "sc.iview:sciview:0.3.0")
        stub = tmp_path / "sc.iview/sciview/0.4.0"
        stub.mkdir()
        (stub / _MARKER).write_text("")
        build_site_maps(tmp_path)
        assert (tmp_path / "latest.map").read_text() == "sc.iview/sciview 0.3.0\n"


class TestNamedUnions:
    def test_named_union_paths_and_landing_page(self, tmp_path):
        comp = _flat(tmp_path)
        bom = _comp("org.scijava:pom-scijava:45.1.0")
        build_union(tmp_path, bom, [comp])
        build_union(tmp_path, bom, [comp], name="org.scijava")
        out = tmp_path / _BOM / "45.1.0" / "org.scijava"
        rows = dict(
            r.split("\t") for r in (out / "redirects.tsv").read_text().splitlines()
        )
        assert rows == {
            "/org.scijava/pom-scijava/45.1.0/org.scijava/org/scijava/Context.html": "/org.scijava/scijava-common/2.99.0/org/scijava/Context.html",
            "/org.scijava/pom-scijava/45.1.0/org.scijava/org/scijava/package-summary.html": "/org.scijava/scijava-common/2.99.0/org/scijava/package-summary.html",
        }
        assert (out / "element-list").read_text() == "org.scijava\n"
        landing = (out / "index.html").read_text()
        assert 'href="../../../../org.scijava/scijava-common/2.99.0/"' in landing
        assert "org.scijava:pom-scijava:45.1.0: org.scijava" in landing

    def test_site_maps_include_named_unions(self, tmp_path):
        old = _flat(tmp_path, "org.scijava:scijava-common:2.98.0")
        (
            tmp_path / "org.scijava/scijava-common/2.98.0/org/scijava/Gone.html"
        ).write_text("")
        new = _flat(tmp_path, "org.scijava:scijava-common:2.99.0")
        for v, comp in (("45.0.0", old), ("45.1.0", new)):
            bom = _comp(f"org.scijava:pom-scijava:{v}")
            build_union(tmp_path, bom, [comp])
            build_union(tmp_path, bom, [comp], name="org.scijava")
        result = build_site_maps(tmp_path)
        redirects = (tmp_path / "redirects.map").read_text()
        # 45.0.0: 3 pages in each of its 2 unions; 45.1.0: 2 in each.
        assert result.redirect_count == 3 + 3 + 2 + 2
        assert (
            "/org.scijava/pom-scijava/45.1.0/org.scijava/org/scijava/Context.html "
            "/org.scijava/scijava-common/2.99.0/org/scijava/Context.html\n"
        ) in redirects
        fallback = (tmp_path / "latest-fallback.map").read_text().splitlines()
        assert sorted(fallback) == [
            (
                "/org.scijava/pom-scijava/latest/org.scijava/org/scijava/Gone.html "
                "/org.scijava/pom-scijava/45.0.0/org.scijava/org/scijava/Gone.html"
            ),
            (
                "/org.scijava/pom-scijava/latest/org/scijava/Gone.html "
                "/org.scijava/pom-scijava/45.0.0/org/scijava/Gone.html"
            ),
        ]

    def test_stale_named_unions_removed(self, tmp_path):
        from pombast.javadoc._pipeline import _remove_stale_unions

        comp = _flat(tmp_path)
        bom = _comp("org.scijava:pom-scijava:45.1.0")
        build_union(tmp_path, bom, [comp])
        build_union(tmp_path, bom, [comp], name="org.scijava")
        build_union(tmp_path, bom, [comp], name="old.group")
        _remove_stale_unions(tmp_path / _BOM / "45.1.0", {"org.scijava"})
        assert (tmp_path / _BOM / "45.1.0" / "org.scijava").is_dir()
        assert not (tmp_path / _BOM / "45.1.0" / "old.group").exists()
        # The union's own files are not named unions.
        assert (tmp_path / _BOM / "45.1.0" / "redirects.tsv").is_file()

    def test_union_names_cannot_look_like_packages(self):
        import pytest

        from pombast.javadoc._union import check_union_name

        for ok in ("net.imagej", "sc.fiji", "bio-formats"):
            assert check_union_name(ok) == ok
        # "ome" is a valid package directory (ome.xml), so it would collide.
        for bad in ("ome", "../x", "a/b", ".hidden", ""):
            with pytest.raises(ValueError):
                check_union_name(bad)


class TestLatest:
    def test_real_release_beats_commit_hash(self, tmp_path):
        for v in ("0.2.0-beta-5", "0.4.0", "9c0918a", "e3510f4"):
            _flat(tmp_path, f"sc.iview:sciview:{v}")
        build_site_maps(tmp_path)
        assert (tmp_path / "latest.map").read_text() == "sc.iview/sciview 0.4.0\n"

    def test_commit_hash_when_no_release(self, tmp_path):
        _flat(tmp_path, "graphics.scenery:bigvolumeviewer:a6b021d")
        build_site_maps(tmp_path)
        assert (tmp_path / "latest.map").read_text() == (
            "graphics.scenery/bigvolumeviewer a6b021d\n"
        )

    def test_date_versions_are_releases(self, tmp_path):
        for v in ("20020414", "20090621"):
            _flat(tmp_path, f"isorelax:isorelax:{v}")
        build_site_maps(tmp_path)
        assert (tmp_path / "latest.map").read_text() == "isorelax/isorelax 20090621\n"


class TestClassifiedOnly:
    def test_ga_managed_only_with_classifier(self, tmp_path):
        from pombast.maven._bom import load_bom

        def dep(a, classifier=""):
            c = f"<classifier>{classifier}</classifier>" if classifier else ""
            return (
                f"<dependency><groupId>org.example</groupId><artifactId>{a}"
                f"</artifactId><version>1.0</version>{c}</dependency>"
            )

        (tmp_path / "pom.xml").write_text(
            '<project xmlns="http://maven.apache.org/POM/4.0.0">'
            "<modelVersion>4.0.0</modelVersion><groupId>org.example</groupId>"
            "<artifactId>bom</artifactId><version>1</version><packaging>pom</packaging>"
            "<dependencyManagement><dependencies>"
            + dep("plain")
            + dep("both")
            + dep("both", "natives-linux")
            + dep("fx", "linux")
            + "</dependencies></dependencyManagement></project>"
        )
        default = {c.name for c in load_bom(str(tmp_path)).components}
        assert default == {"plain", "both"}
        javadoc = load_bom(str(tmp_path), classified_only=True).components
        assert sorted(c.name for c in javadoc) == ["both", "fx", "plain"]
