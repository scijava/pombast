"""Version filter rules from a versions-maven-plugin rules.xml file."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fnmatch import fnmatch
from functools import cmp_to_key
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class _Rule:
    group_pattern: str
    artifact_pattern: str
    ignore_patterns: list[tuple[bool, str]] = field(default_factory=list)


class RulesXML:
    """Version filter rules from a versions-maven-plugin rules.xml file.

    Supports exact and regex <ignoreVersion> patterns with glob-style
    groupId/artifactId matching (e.g. artifactId="*").
    """

    def __init__(self, rules: list[_Rule]):
        self._rules = rules

    @classmethod
    def load(cls, source: str | Path) -> RulesXML:
        """Load rules from a file path or HTTP(S) URL."""
        src = str(source)
        if src.startswith("http://") or src.startswith("https://"):
            resp = requests.get(src, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        else:
            root = ET.parse(source).getroot()

        # Strip XML namespace prefixes so xpath queries work without them.
        for el in root.iter():
            if el.tag.startswith("{"):
                el.tag = el.tag[el.tag.find("}") + 1 :]

        rules: list[_Rule] = []
        for rule_el in root.findall(".//rule"):
            g = rule_el.get("groupId", "*")
            a = rule_el.get("artifactId", "*")
            ignores: list[tuple[bool, str]] = []
            for iv in rule_el.findall("ignoreVersions/ignoreVersion"):
                is_regex = iv.get("type") == "regex"
                ignores.append((is_regex, iv.text or ""))
            rules.append(_Rule(g, a, ignores))

        return cls(rules)

    @classmethod
    def empty(cls) -> RulesXML:
        """Return an instance that ignores nothing (accepts all versions)."""
        return cls([])

    def is_ignored(self, group_id: str, artifact_id: str, version: str) -> bool:
        """Return True if version should be excluded for this G:A."""
        for rule in self._rules:
            if not fnmatch(group_id, rule.group_pattern):
                continue
            if not fnmatch(artifact_id, rule.artifact_pattern):
                continue
            for is_regex, pattern in rule.ignore_patterns:
                if is_regex:
                    if re.fullmatch(pattern, version):
                        return True
                else:
                    if version == pattern:
                        return True
        return False

    def latest_acceptable(
        self,
        group_id: str,
        artifact_id: str,
        versions: list[str],
    ) -> str | None:
        """Return the newest non-ignored non-SNAPSHOT release version."""
        from jgo.maven import compare_versions

        candidates = [
            v
            for v in versions
            if not v.endswith("-SNAPSHOT")
            and not self.is_ignored(group_id, artifact_id, v)
        ]
        if not candidates:
            return None
        return max(candidates, key=cmp_to_key(compare_versions))
