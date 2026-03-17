"""Tests for BOM loading."""

from pathlib import Path

import pytest

from bombast.maven._bom import load_bom

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestLoadBom:
    def test_load_local_bom(self):
        """Load a BOM from a local directory with a pom.xml."""
        bom_dir = FIXTURES_DIR / "sample-bom"
        components = load_bom(str(bom_dir))

        # Should find 3 jar-type managed dependencies
        assert len(components) == 3

        # Verify components are sorted by (groupId, artifactId)
        gas = [(c.group, c.name) for c in components]
        assert gas == sorted(gas)

        # Verify property interpolation worked
        by_name = {c.name: c for c in components}
        assert by_name["alpha"].version == "1.2.3"
        assert by_name["beta"].version == "4.5.6"
        assert by_name["gamma"].version == "7.8.9"

    def test_load_local_bom_groups(self):
        """Verify correct group assignment."""
        bom_dir = FIXTURES_DIR / "sample-bom"
        components = load_bom(str(bom_dir))

        by_name = {c.name: c for c in components}
        assert by_name["alpha"].group == "org.example"
        assert by_name["gamma"].group == "com.other"

    def test_load_local_bom_skips_pom_type(self):
        """Pom-only dependencies should be excluded."""
        bom_dir = FIXTURES_DIR / "sample-bom"
        components = load_bom(str(bom_dir))

        names = [c.name for c in components]
        assert "parent-pom" not in names

    def test_load_missing_directory(self):
        """Loading from a nonexistent directory should fail."""
        with pytest.raises(FileNotFoundError):
            load_bom("/nonexistent/path")

    def test_load_invalid_coordinate(self):
        """A coordinate with fewer than 3 parts should fail."""
        with pytest.raises(ValueError, match="G:A:V"):
            load_bom("org.scijava:pom-scijava")

    def test_scm_not_populated_by_default(self):
        """SCM info is not populated during BOM loading (done later in SCM resolution)."""
        bom_dir = FIXTURES_DIR / "sample-bom"
        components = load_bom(str(bom_dir))

        for c in components:
            assert c.scm_url is None
            assert c.scm_tag is None
