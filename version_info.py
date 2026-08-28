# -*- coding: utf-8 -*-
"""Runtime version/build info for the plugin.

Merges the manually-managed version from metadata.txt with the auto-generated
build stamp (build_info.json, written by the git hooks in scripts/git-hooks on
every commit/checkout/merge). Stdlib only — safe to import eagerly and usable
headless.

The plugin never reads .git at runtime: deployed copies live outside the repo
and may sit on an unrelated checkout. If the stamp file is missing (e.g. a
fresh clone whose hooks haven't fired yet), everything degrades to
"unknown build".
"""

import configparser
import json
import os
from dataclasses import dataclass
from typing import Optional

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass(frozen=True)
class VersionInfo:
    name: str
    version: str
    author: str
    commit: Optional[str] = None
    commit_full: Optional[str] = None
    branch: Optional[str] = None
    date: Optional[str] = None
    commit_count: Optional[int] = None


_cached_info = None


def get_version_info() -> VersionInfo:
    """Read metadata.txt + build_info.json once and cache. Never raises."""
    global _cached_info
    if _cached_info is not None:
        return _cached_info

    name = "Linear Geoscience Mapping Tools"
    version = "?"
    author = "Harry West"
    try:
        parser = configparser.ConfigParser()
        parser.read(os.path.join(_PLUGIN_DIR, "metadata.txt"), encoding="utf-8")
        general = parser["general"]
        name = general.get("name", name)
        version = general.get("version", version)
        author = general.get("author", author)
    except Exception:
        pass

    commit = commit_full = branch = date = None
    commit_count = None
    try:
        with open(os.path.join(_PLUGIN_DIR, "build_info.json"), encoding="utf-8") as f:
            stamp = json.load(f)
        commit = stamp.get("commit") or None
        commit_full = stamp.get("commit_full") or None
        branch = stamp.get("branch") or None
        date = stamp.get("date") or None
        raw_count = stamp.get("commit_count")
        commit_count = int(raw_count) if raw_count is not None else None
    except Exception:
        pass

    _cached_info = VersionInfo(
        name=name, version=version, author=author,
        commit=commit, commit_full=commit_full, branch=branch,
        date=date, commit_count=commit_count,
    )
    return _cached_info


def short_version_string() -> str:
    """e.g. "4.0 (bb325ea · 2026-07-14)" or "4.0 (unknown build)"."""
    info = get_version_info()
    if info.commit:
        parts = [info.commit]
        if info.date:
            parts.append(info.date)
        return "{} ({})".format(info.version, " · ".join(parts))
    return "{} (unknown build)".format(info.version)


def footer_text() -> str:
    """Multi-line text for the sidebar footer label."""
    info = get_version_info()
    return "{}\nVersion {}\nAuthor: {}".format(
        info.name, short_version_string(), info.author
    )
