"""Integration test for mega-melt's duplicate-class detection.

Uses the duplicate-classes fixture (a POM that depends directly on both
log4j and reload4j, which both provide org.apache.log4j.* classes) to
confirm that pom-scijava's banDuplicateClasses enforcer rule — the rule
mega-melt validation relies on to catch classpath conflicts across a BOM
(see README's mega-melt section) — actually fires.

This runs a real Maven build against Maven Central and is intentionally
slow.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pombast.maven._builder import locate_java
from pombast.maven._mega_melt import run_mega_melt_validation

FIXTURE = Path(__file__).parent.parent / "fixtures" / "duplicate-classes"

# pom-scijava's parent chain requires Java 11+; pin it explicitly so this
# test doesn't spuriously fail on an older ambient JDK before ever reaching
# the duplicate-classes rule.
_JAVA_VERSION = 11


def test_duplicate_classes_fail_enforcer(tmp_path):
    """log4j + reload4j together should trip banDuplicateClasses."""
    mega_melt_dir = tmp_path / "duplicate-classes"
    shutil.copytree(FIXTURE, mega_melt_dir)

    java_home = locate_java(_JAVA_VERSION)
    success, _tree_log, build_log = run_mega_melt_validation(
        mega_melt_dir, java_home=java_home
    )

    assert not success, "expected enforcer to fail on duplicate classes"

    log_content = build_log.read_text(encoding="utf-8")
    assert "BanDuplicateClasses" in log_content, (
        f"expected a BanDuplicateClasses enforcer failure, but got:\n{log_content}"
    )
    assert "ch.qos.reload4j:reload4j" in log_content
    assert "log4j:log4j" in log_content
