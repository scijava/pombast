"""Tests for rules.xml version filtering."""

from pombast.maven._rules import RulesXML


class TestAcceptableAbove:
    def test_returns_newer_only_newest_first(self):
        rules = RulesXML.empty()
        versions = ["1.0", "1.1", "2.0", "2.1"]
        assert rules.acceptable_above("g", "a", versions, "1.1") == ["2.1", "2.0"]

    def test_excludes_snapshots(self):
        rules = RulesXML.empty()
        versions = ["1.0", "2.0-SNAPSHOT", "2.0"]
        assert rules.acceptable_above("g", "a", versions, "1.0") == ["2.0"]

    def test_empty_when_current_is_latest(self):
        rules = RulesXML.empty()
        assert rules.acceptable_above("g", "a", ["1.0", "1.1"], "1.1") == []

    def test_applies_ignore_rules(self):
        # Build a ruleset that ignores anything not starting with "1.".
        from pombast.maven._rules import RulesXML, _Rule

        rules = RulesXML([_Rule("g", "a", [(True, r"^(?!1\.).*")])])
        versions = ["1.0", "1.5", "2.0"]
        # 2.0 is ignored; only 1.5 is newer-and-accepted above 1.0.
        assert rules.acceptable_above("g", "a", versions, "1.0") == ["1.5"]
