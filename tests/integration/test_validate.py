"""Integration tests for the validate subcommand using the minibom fixture.

These tests run real Maven builds and therefore populate ~/.m2, ~/.cache/jgo,
and ~/.cache/cjdk caches.  They are intentionally slow.
"""

from __future__ import annotations

import re
from pathlib import Path

from pombast.config._settings import PipelineConfig
from pombast.core._component import BuildStatus
from pombast.core._pipeline import Pipeline

MINIBOM = Path(__file__).parent.parent / "fixtures" / "minibom"

# scijava-common depends on parsington, making it the right component to test
# the BOM's dependency version pinning.
_SCJ_COMMON = "org.scijava:scijava-common"

# parsington 1.0.0 predates the 3.x API that scijava-common 2.99.2 requires,
# so injecting it should cause a compilation failure.
_PARSINGTON_INCOMPATIBLE = "org.scijava:parsington:1.0.0"


def _make_pipeline(tmp_path: Path, **kwargs) -> Pipeline:
    config = PipelineConfig(
        bom=str(MINIBOM),
        output_dir=tmp_path / "output",
        success_cache_dir=tmp_path / ".success-cache",
        test_binary=False,
        force=True,
        **kwargs,
    )
    return Pipeline(config)


class TestValidate:
    def test_passing_bom(self, tmp_path):
        """scijava-common should build successfully against the minibom."""
        pipeline = _make_pipeline(tmp_path, includes=[_SCJ_COMMON])
        report = pipeline.run()

        assert report.results, "expected at least one result"
        failures = [r for r in report.results if r.status != BuildStatus.SUCCESS]
        assert not failures, (
            f"unexpected failures: {[r.component.coordinate for r in failures]}"
        )

    def test_incompatible_parsington(self, tmp_path):
        """Injecting parsington 1.0.0 via -c should cause scijava-common to fail."""
        pipeline = _make_pipeline(
            tmp_path,
            includes=[_SCJ_COMMON],
            changes=[_PARSINGTON_INCOMPATIBLE],
        )
        report = pipeline.run()

        failures = [
            r
            for r in report.results
            if r.status in (BuildStatus.FAILURE, BuildStatus.ERROR)
        ]
        assert failures, (
            "expected validation failure when building scijava-common against "
            f"parsington 1.0.0, but got: {[r.status for r in report.results]}"
        )

        all_logs = []
        for failure in failures:
            try:
                log_content = Path(failure.log_path).read_text(encoding="utf-8")
                all_logs.append(log_content)
            except Exception as e:
                print(f"Warning: Could not read failure log at {failure.log_path}: {e}")

        log_content_to_check = "\n\n".join(all_logs)

        expected_incompatibility_regex = r"package org\.scijava\.parsington does not exist|cannot find symbol class Token|cannot find symbol class DefaultTreeEvaluator"

        assert re.search(
            expected_incompatibility_regex, log_content_to_check, re.IGNORECASE
        ), (
            f"expected compilation failure matching signature {expected_incompatibility_regex}, "
            f"but found unexpected build log content."
        )
