"""Tests for core component types."""

from bombast.core import BuildResult, BuildStatus, Component, ValidationReport


class TestComponent:
    def test_coordinate(self):
        c = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        assert c.coordinate == "org.scijava:scijava-common:2.99.0"

    def test_ga(self):
        c = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        assert c.ga == "org.scijava:scijava-common"

    def test_str(self):
        c = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        assert str(c) == "org.scijava:scijava-common:2.99.0"

    def test_frozen(self):
        c = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        try:
            c.version = "3.0.0"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass

    def test_equality(self):
        c1 = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        c2 = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        assert c1 == c2

    def test_hash(self):
        c1 = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        c2 = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        assert hash(c1) == hash(c2)
        assert len({c1, c2}) == 1

    def test_optional_fields(self):
        c = Component(
            group="org.scijava",
            name="scijava-common",
            version="2.99.0",
            scm_url="https://github.com/scijava/scijava-common",
            scm_tag="scijava-common-2.99.0",
            java_version=11,
        )
        assert c.scm_url == "https://github.com/scijava/scijava-common"
        assert c.scm_tag == "scijava-common-2.99.0"
        assert c.java_version == 11


class TestBuildResult:
    def test_ok_success(self):
        c = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        r = BuildResult(component=c, status=BuildStatus.SUCCESS)
        assert r.ok

    def test_ok_skipped(self):
        c = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        r = BuildResult(
            component=c,
            status=BuildStatus.SKIPPED,
            skipped_reason="prior success",
        )
        assert r.ok

    def test_not_ok_failure(self):
        c = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        r = BuildResult(component=c, status=BuildStatus.FAILURE)
        assert not r.ok

    def test_not_ok_error(self):
        c = Component(group="org.scijava", name="scijava-common", version="2.99.0")
        r = BuildResult(component=c, status=BuildStatus.ERROR)
        assert not r.ok


class TestValidationReport:
    def test_empty_report(self):
        report = ValidationReport(bom="org.scijava:pom-scijava:37.0.0")
        assert report.successes == []
        assert report.failures == []
        assert report.errors == []
        assert report.skipped == []

    def test_categorization(self):
        c1 = Component(group="org.scijava", name="a", version="1.0")
        c2 = Component(group="org.scijava", name="b", version="1.0")
        c3 = Component(group="org.scijava", name="c", version="1.0")
        c4 = Component(group="org.scijava", name="d", version="1.0")

        report = ValidationReport(
            bom="test:bom:1.0",
            results=[
                BuildResult(component=c1, status=BuildStatus.SUCCESS),
                BuildResult(component=c2, status=BuildStatus.FAILURE),
                BuildResult(component=c3, status=BuildStatus.SKIPPED),
                BuildResult(component=c4, status=BuildStatus.ERROR),
            ],
        )
        assert len(report.successes) == 1
        assert len(report.failures) == 1
        assert len(report.skipped) == 1
        assert len(report.errors) == 1

    def test_summary(self):
        report = ValidationReport(bom="test:bom:1.0")
        summary = report.summary()
        assert "test:bom:1.0" in summary
        assert "Total: 0" in summary
