"""Tests for smelt.json serialization."""

from pombast.core import BuildResult, BuildStatus, Component, ValidationReport
from pombast.core._smelt_json import report_to_dict
from pombast.maven._java_version import JavaVersionAnalysis


def _component(name: str, version: str = "1.0.0") -> Component:
    return Component(group="org.scijava", name=name, version=version)


class TestReportToDict:
    def test_schema_version(self):
        report = ValidationReport(bom="org.scijava:pom-scijava:40.0.0")
        data = report_to_dict(report)
        assert data["version"] == 2
        assert data["bom"] == "org.scijava:pom-scijava:40.0.0"
        assert data["components"] == {}

    def test_component_keyed_by_ga(self):
        report = ValidationReport(
            bom="test:bom:1.0",
            results=[
                BuildResult(component=_component("foo"), status=BuildStatus.SUCCESS)
            ],
        )
        data = report_to_dict(report)
        assert "org.scijava:foo" in data["components"]
        entry = data["components"]["org.scijava:foo"]
        assert entry["version"] == "1.0.0"
        assert entry["source_build"] == "pass"

    def test_bytecode_fields_omitted_without_analysis(self):
        report = ValidationReport(
            bom="test:bom:1.0",
            results=[
                BuildResult(
                    component=_component("foo"),
                    status=BuildStatus.SKIPPED,
                    skipped_reason="prior success",
                )
            ],
        )
        entry = report_to_dict(report)["components"]["org.scijava:foo"]
        assert "own_bytecode" not in entry
        assert "effective_bytecode" not in entry
        assert "closure" not in entry

    def test_bytecode_fields_present_with_analysis(self):
        analysis = JavaVersionAnalysis(
            java_version=21,
            raw_max=21,
            own_bytecode=17,
            drivers=["net.imagej:imagej-common:2.0.0"],
            closure=["net.imagej:imagej-common::jar:2.0.0"],
        )
        report = ValidationReport(
            bom="test:bom:1.0",
            results=[
                BuildResult(
                    component=_component("foo"),
                    status=BuildStatus.SUCCESS,
                    analysis=analysis,
                )
            ],
        )
        entry = report_to_dict(report)["components"]["org.scijava:foo"]
        assert entry["own_bytecode"] == 17
        assert entry["effective_bytecode"] == 21
        assert entry["build_java"] == 21
        assert entry["drivers"] == ["net.imagej:imagej-common:2.0.0"]
        assert entry["closure"] == ["net.imagej:imagej-common::jar:2.0.0"]
