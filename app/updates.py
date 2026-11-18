"""Check GitHub for a newer release (only when config.GITHUB_REPO is set)."""

from __future__ import annotations

import re

import requests

from . import __version__, config


def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def newer_release() -> tuple[str, str] | None:
    """Return (version, page_url) if a newer release exists, else None."""
    if not config.GITHUB_REPO:
        return None
    r = requests.get(
        f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": config.APP_NAME},
        timeout=10,
    )
    if r.status_code != 200:
        return None
    data = r.json()
    tag = data.get("tag_name", "")
    if tag and _parse(tag) > _parse(__version__):
        return tag.lstrip("v"), data.get("html_url", "")
    return None
