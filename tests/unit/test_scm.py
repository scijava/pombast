"""Tests for SCM URL/tag extraction."""

from unittest.mock import MagicMock, patch

from bombast.maven._scm import _extract_scm_tag, _extract_scm_url, _guess_tag


class TestExtractScmUrl:
    def test_scm_connection(self):
        pom = MagicMock()
        pom.value.return_value = "scm:git:https://github.com/scijava/scijava-common"
        pom.scmURL = None

        assert _extract_scm_url(pom) == "https://github.com/scijava/scijava-common"

    def test_scm_git_protocol(self):
        pom = MagicMock()
        pom.value.return_value = "scm:git:git://github.com/scijava/scijava-common"
        pom.scmURL = None

        assert _extract_scm_url(pom) == "https://github.com/scijava/scijava-common"

    def test_scm_url_fallback(self):
        pom = MagicMock()
        pom.value.return_value = None
        pom.scmURL = "https://github.com/scijava/scijava-common"

        assert _extract_scm_url(pom) == "https://github.com/scijava/scijava-common"

    def test_no_scm(self):
        pom = MagicMock()
        pom.value.return_value = None
        pom.scmURL = None

        assert _extract_scm_url(pom) is None


class TestExtractScmTag:
    def test_proper_tag(self):
        pom = MagicMock()
        pom.value.return_value = "scijava-common-2.99.0"

        assert _extract_scm_tag(pom) == "scijava-common-2.99.0"

    def test_head_tag(self):
        pom = MagicMock()
        pom.value.return_value = "HEAD"

        assert _extract_scm_tag(pom) is None

    def test_no_tag(self):
        pom = MagicMock()
        pom.value.return_value = None

        assert _extract_scm_tag(pom) is None


class TestGuessTag:
    @patch("bombast.maven._scm.ls_remote_tags")
    def test_artifact_version_tag(self, mock_ls):
        mock_ls.return_value = [
            "scijava-common-2.98.0",
            "scijava-common-2.99.0",
            "scijava-common-3.0.0",
        ]

        assert _guess_tag("url", "scijava-common", "2.99.0") == "scijava-common-2.99.0"

    @patch("bombast.maven._scm.ls_remote_tags")
    def test_version_only_tag(self, mock_ls):
        mock_ls.return_value = ["1.0.0", "2.0.0", "3.0.0"]

        assert _guess_tag("url", "some-artifact", "2.0.0") == "2.0.0"

    @patch("bombast.maven._scm.ls_remote_tags")
    def test_v_prefixed_tag(self, mock_ls):
        mock_ls.return_value = ["v1.0.0", "v2.0.0", "v3.0.0"]

        assert _guess_tag("url", "some-artifact", "2.0.0") == "v2.0.0"

    @patch("bombast.maven._scm.ls_remote_tags")
    def test_preference_order(self, mock_ls):
        """artifactId-version is preferred over bare version."""
        mock_ls.return_value = ["my-lib-1.0", "1.0", "v1.0"]

        assert _guess_tag("url", "my-lib", "1.0") == "my-lib-1.0"

    @patch("bombast.maven._scm.ls_remote_tags")
    def test_no_matching_tag(self, mock_ls):
        mock_ls.return_value = ["unrelated-1.0", "other-2.0"]

        assert _guess_tag("url", "my-lib", "3.0") is None

    @patch("bombast.maven._scm.ls_remote_tags")
    def test_no_tags_at_all(self, mock_ls):
        mock_ls.return_value = []

        assert _guess_tag("url", "my-lib", "1.0") is None
