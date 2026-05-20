"""Extract developer metadata from component POM files."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from jgo.maven import MavenContext

_log = logging.getLogger(__name__)
_POM_NS = "http://maven.apache.org/POM/4.0.0"


@dataclass(frozen=True)
class Developer:
    id: str
    name: str
    url: str


def _pom_cache_path(ctx: MavenContext, g: str, a: str, v: str) -> Path:
    return Path(ctx.repo_cache) / g.replace(".", "/") / a / v / f"{a}-{v}.pom"


def _download_pom(g: str, a: str, v: str, repos: dict[str, str]) -> bytes | None:
    group_path = g.replace(".", "/")
    rel = f"{group_path}/{a}/{v}/{a}-{v}.pom"
    for base in repos.values():
        url = f"{base.rstrip('/')}/{rel}"
        try:
            resp = requests.get(url, timeout=30)
            if resp.ok:
                _log.debug("Downloaded POM from %s", url)
                return resp.content
        except requests.RequestException:
            pass
    return None


def _tag(name: str, ns: str | None) -> str:
    return f"{{{ns}}}{name}" if ns else name


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_developers(root: ET.Element) -> list[tuple[Developer, set[str]]]:
    ns = _POM_NS if root.tag.startswith("{") else None

    devs_el = root.find(_tag("developers", ns))
    if devs_el is None:
        return []

    result = []
    for dev_el in devs_el:
        dev_id = _text(dev_el.find(_tag("id", ns)))
        if not dev_id:
            continue
        dev_name = _text(dev_el.find(_tag("name", ns)))
        dev_url = _text(dev_el.find(_tag("url", ns)))
        roles_el = dev_el.find(_tag("roles", ns))
        roles: set[str] = set()
        if roles_el is not None:
            for role_el in roles_el:
                r = (role_el.text or "").strip()
                if r:
                    roles.add(r)
        result.append((Developer(id=dev_id, name=dev_name, url=dev_url), roles))

    return result


def fetch_developers(
    ctx: MavenContext,
    g: str,
    a: str,
    v: str,
    repos: dict[str, str],
) -> list[tuple[Developer, set[str]]]:
    """Return (Developer, roles) pairs parsed from the component POM at G:A:V."""
    cache_path = _pom_cache_path(ctx, g, a, v)
    if not cache_path.exists():
        content = _download_pom(g, a, v, repos)
        if content is None:
            _log.warning("Could not obtain POM for %s:%s:%s", g, a, v)
            return []
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)

    try:
        root = ET.parse(cache_path).getroot()
        return _parse_developers(root)
    except ET.ParseError as e:
        _log.warning("Failed to parse POM %s: %s", cache_path, e)
        return []
