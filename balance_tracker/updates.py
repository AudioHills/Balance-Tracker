"""Check GitHub Releases for a newer version of the desktop app.

Only runs when the user clicks "Check for updates"; nothing about the user's data is sent.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from . import REPO, __version__

API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"


@dataclass(frozen=True)
class Release:
    version: str
    url: str  # release page to download it from
    name: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """"v2.0.1" -> (2, 0, 1). Stops at the first part that isn't a number ("2.1.0-beta" -> (2, 1, 0))."""
    parts = []
    for piece in text.strip().lstrip("vV").split("."):
        m = re.match(r"\d+", piece)
        if not m:
            break
        parts.append(int(m.group()))
        if m.end() < len(piece):
            break
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def latest_release(timeout: float = 10, opener=urllib.request.urlopen) -> Release:
    """The newest published release. Raises OSError (or ValueError for an odd reply) on failure."""
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"BalanceTracker/{__version__}",
    })
    with opener(req, timeout=timeout) as r:
        info = json.loads(r.read().decode("utf-8"))
    tag = str(info.get("tag_name") or "")
    if not parse_version(tag):
        raise ValueError(f"Unexpected release tag {tag!r}")
    return Release(version=tag.lstrip("vV"), url=str(info.get("html_url") or RELEASES_URL),
                   name=str(info.get("name") or ""))
