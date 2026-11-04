"""Tests for the javadoc pipeline's orchestration, with its phases stubbed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pombast.javadoc._pipeline as pipeline_mod
from pombast.core import Component
from pombast.javadoc._crosslink import CrosslinkResult, CrosslinkStatus
from pombast.javadoc._deps import Closure
from pombast.javadoc._pipeline import JavadocPipeline, JavadocRunConfig
from pombast.javadoc._site import SiteMapsResult
from pombast.javadoc._union import UnionResult
from pombast.javadoc._unpack import UnpackResult, UnpackStatus
from pombast.maven._bom import BomData

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

FX19 = Component.parse("org.openjfx:javafx-base:19.0.2.1")
FX25 = Component.parse("org.openjfx:javafx-base:25.0.5")
FX25_DEP = Component.parse("org.example:fx25-dep:1.0")


def _run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extras: list[str]
) -> tuple[dict[str, list[Component]], dict[str | None, list[Component]]]:
    """Run the pipeline over a BOM managing FX19; return what each phase saw."""
    seen: dict[str, list[Component]] = {
        "resolved": [],
        "unpacked": [],
        "crosslinked": [],
    }
    unions: dict[str | None, list[Component]] = {}

    def load_bom(bom, **_kw):
        return BomData([FX19], {}, None, tmp_path / "pom.xml")

    def resolve_closure(_ctx, comp):
        seen["resolved"].append(comp)
        return Closure(deps=[FX25_DEP] if comp == FX25 else [])

    def unpack_component(_ctx, comp, _site, **_kw):
        seen["unpacked"].append(comp)
        return UnpackResult(comp, UnpackStatus.UNPACKED)

    def crosslink_component(_site, comp, *_a, **_kw):
        seen["crosslinked"].append(comp)
        return CrosslinkResult(comp, CrosslinkStatus.CROSSLINKED)

    def build_union(site, _bom, members, *, name=None, **_kw):
        unions[name] = list(members)
        return UnionResult(union_dir=site / "union")

    monkeypatch.setattr(pipeline_mod, "load_bom", load_bom)
    monkeypatch.setattr(pipeline_mod, "resolve_closure", resolve_closure)
    monkeypatch.setattr(pipeline_mod, "unpack_component", unpack_component)
    monkeypatch.setattr(pipeline_mod, "crosslink_component", crosslink_component)
    monkeypatch.setattr(pipeline_mod, "build_union", build_union)
    monkeypatch.setattr(pipeline_mod, "build_site_maps", lambda _site: SiteMapsResult())

    config = JavadocRunConfig(
        bom="org.scijava:pom-scijava:45.1.0",
        output_dir=tmp_path / "site",
        workers=1,
        unions={"org.openjfx": ["org.openjfx:*"]},
        extras=extras,
    )
    JavadocPipeline(config).run()
    return seen, unions


class TestExtras:
    def test_extras_are_published_but_join_no_union(self, monkeypatch, tmp_path):
        seen, unions = _run(monkeypatch, tmp_path, [FX25.coordinate])
        for phase in ("resolved", "unpacked", "crosslinked"):
            assert set(seen[phase]) == {FX19, FX25, FX25_DEP}, phase
        assert unions == {None: [FX19], "org.openjfx": [FX19]}

    def test_extra_the_bom_manages_is_not_duplicated(self, monkeypatch, tmp_path):
        seen, _ = _run(monkeypatch, tmp_path, [FX19.coordinate, FX19.coordinate])
        assert seen["unpacked"] == [FX19]
