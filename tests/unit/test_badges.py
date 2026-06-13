"""Tests for badges.json output."""

import json

from pombast.badges._fetch import write_badges_json


def test_repos_sorted_regardless_of_insertion_order(tmp_path):
    # Insert slugs out of alphabetical order, as as_completed would.
    badges = {
        "zebra/z": {"title": "passing", "workflow": "build.yml"},
        "alpha/a": {"title": "failing", "workflow": "build.yml"},
        "mid/m": {"title": "passing", "workflow": "ci.yml"},
    }
    out = tmp_path / "badges.json"
    write_badges_json(badges, out)

    data = json.loads(out.read_text())
    assert list(data["repos"]) == ["alpha/a", "mid/m", "zebra/z"]
    # Per-entry keys are deterministic too.
    assert list(data["repos"]["alpha/a"]) == ["title", "workflow"]


def test_output_is_stable_across_runs(tmp_path):
    a = {
        "b/b": {"title": "x", "workflow": "build.yml"},
        "a/a": {"title": "y", "workflow": "build.yml"},
    }
    b = {
        "a/a": {"title": "y", "workflow": "build.yml"},
        "b/b": {"title": "x", "workflow": "build.yml"},
    }
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    write_badges_json(a, out_a)
    write_badges_json(b, out_b)

    # Strip the volatile "generated" line; the rest must be byte-identical.
    def repos_block(p):
        return "\n".join(
            line for line in p.read_text().splitlines() if '"generated"' not in line
        )

    assert repos_block(out_a) == repos_block(out_b)
