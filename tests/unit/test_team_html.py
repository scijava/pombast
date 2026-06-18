"""Tests for team.json data building and the static HTML shell."""

import json

from pombast.team._github import RepoItem
from pombast.team._html import build_team_data, generate_team_html, write_team_json
from pombast.team._pom_devs import Developer
from pombast.team._workload import DeveloperRow


def _row(dev_id, *, prs=0, components=None):
    dev = Developer(id=dev_id, name=dev_id.title(), url="")
    row = DeveloperRow(developer=dev)
    for i in range(prs):
        url = f"https://github.com/org/repo/pull/{dev_id}{i}"
        row._prs[url] = RepoItem(url=url, title=f"PR {i}", number=i, repo="org/repo")
    for ga in components or []:
        row.components.append(ga)
        row._component_urls[ga] = f"https://github.com/org/{ga}"
    return row


class TestBuildTeamData:
    def test_rows_sorted_by_dev_id(self):
        rows = [_row("zoe", prs=5), _row("amy", prs=1), _row("bob", prs=3)]
        data = build_team_data(rows, generated="2026-06-18 00:00 UTC")
        ids = [r["dev_id"] for r in data["rows"]]
        assert ids == ["amy", "bob", "zoe"]
        assert data["generated"] == "2026-06-18 00:00 UTC"

    def test_row_shape_and_popups(self):
        data = build_team_data([_row("amy", prs=2, components=["g:a"])])
        row = data["rows"][0]
        assert row["dev_name"] == "Amy"
        assert row["dev_url"] == "https://github.com/amy"
        assert row["reviewer_prs"] == 2
        assert row["total"] == 2
        assert row["component_count"] == 1
        assert len(row["popups"]["reviewer_prs"]) == 2
        assert row["popups"]["components"][0]["ga"] == "g:a"

    def test_json_is_deterministic(self, tmp_path):
        rows = [_row("bob", prs=2), _row("amy", prs=1)]
        data = build_team_data(rows, generated="t")
        p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
        write_team_json(p1, data)
        write_team_json(p2, build_team_data(list(reversed(rows)), generated="t"))
        assert p1.read_text() == p2.read_text()
        # Valid JSON, trailing newline, sorted keys.
        text = p1.read_text()
        assert text.endswith("\n")
        json.loads(text)


class TestGenerateTeamHtml:
    def test_static_shell_has_no_embedded_data(self):
        html = generate_team_html(data_url="team.json")
        assert "fetch('team.json')" in html
        assert '<tbody id="team-body"></tbody>' in html
        # No developer data baked into the page.
        assert "popup_data" not in html
