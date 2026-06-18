"""Tests for bytecode floor computation in _apply_floors."""

from pombast.maven import _java_version
from pombast.maven._java_version import JavaVersionAnalysis, _apply_floors


def test_drivers_sorted_regardless_of_artifact_order(monkeypatch):
    """drivers must be sorted so smelt.json diffs stay minimal across runs.

    jgo's resolution order is not stable, so the artifact iteration order feeding
    _apply_floors varies run to run. The recorded drivers list must not.
    """
    # All at the same (max) bytecode level so every coordinate is a driver.
    bytecode = {
        "org.scijava:scijava-common:2.100.1": 52,
        "net.imglib2:imglib2:8.0.0": 52,
        "jitk:jitk-tps:3.0.4": 52,
        "org.ejml:ejml-core:0.41": 52,
    }
    monkeypatch.setattr(
        _java_version, "jar_java_version", lambda artifact, **_: bytecode[artifact]
    )

    # Feed coordinates in deliberately non-alphabetic order.
    artifacts = [(coord, coord) for coord in bytecode]

    analysis = JavaVersionAnalysis()
    _apply_floors(analysis, artifacts, own_coordinate="org.scijava:scijava-common:2.100.1")

    assert analysis.drivers == sorted(bytecode)
    assert analysis.raw_max == 52


def test_drivers_only_includes_max_bytecode_artifacts(monkeypatch):
    bytecode = {
        "b:high:1": 61,
        "a:low:1": 52,
        "c:high:1": 61,
    }
    monkeypatch.setattr(
        _java_version, "jar_java_version", lambda artifact, **_: bytecode[artifact]
    )
    artifacts = [(coord, coord) for coord in bytecode]

    analysis = JavaVersionAnalysis()
    _apply_floors(analysis, artifacts, own_coordinate="a:low:1")

    assert analysis.drivers == ["b:high:1", "c:high:1"]
    assert analysis.raw_max == 61
