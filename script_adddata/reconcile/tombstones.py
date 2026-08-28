#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Delete tombstones (pure JSON store).

A propagated delete removes a feature from the master. Because field deletes are
hard deletes (no soft-delete column, per the chosen conventions), we keep an
audit/recovery record of every feature reconcile removes — its attributes and
geometry (WKB hex) — beside the master:

    <master_dir>/adddata_metadata/<master_stem>_tombstones.json

commit.py builds the records (it has the live feature); the engine writes them
only after the layer's delete actually commits. `purge_tombstones` trims old
records once they are no longer needed for recovery.
"""

import os
import json
from datetime import datetime, timezone, timedelta

try:  # package context
    from .checkout import metadata_folder, master_stem, atomic_write_json
except ImportError:  # standalone (headless tests)
    from checkout import metadata_folder, master_stem, atomic_write_json

SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tombstones_path(master_gpkg: str) -> str:
    return os.path.join(metadata_folder(master_gpkg),
                        f"{master_stem(master_gpkg)}_tombstones.json")


def _load(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("entries", [])
                return data
        except (json.JSONDecodeError, IOError):
            pass
    return {"version": SCHEMA_VERSION, "created": _utc_now(), "entries": []}


def _save(path: str, data: dict):
    data["last_updated"] = _utc_now()
    atomic_write_json(path, data)


def append_tombstones(master_gpkg: str, records: list) -> int:
    """Append deleted-feature records. Returns the new total count."""
    if not records:
        return count_tombstones(master_gpkg)
    path = tombstones_path(master_gpkg)
    data = _load(path)
    for r in records:
        r.setdefault("deleted_utc", _utc_now())
    data["entries"].extend(records)
    _save(path, data)
    return len(data["entries"])


def load_tombstones(master_gpkg: str) -> list:
    return _load(tombstones_path(master_gpkg))["entries"]


def count_tombstones(master_gpkg: str) -> int:
    path = tombstones_path(master_gpkg)
    return len(_load(path)["entries"]) if os.path.exists(path) else 0


def purge_tombstones(master_gpkg: str, older_than_days: float = None,
                     before_utc: str = None) -> int:
    """Drop tombstones older than a cutoff. Returns the number removed.

    Provide either `older_than_days` (relative) or `before_utc` (ISO-8601).
    With neither, removes all tombstones.
    """
    path = tombstones_path(master_gpkg)
    if not os.path.exists(path):
        return 0
    data = _load(path)
    entries = data["entries"]

    if before_utc is not None:
        cutoff = before_utc
    elif older_than_days is not None:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=older_than_days)).isoformat()
    else:
        cutoff = None

    if cutoff is None:
        removed = len(entries)
        data["entries"] = []
    else:
        kept = [e for e in entries if str(e.get("deleted_utc", "")) >= cutoff]
        removed = len(entries) - len(kept)
        data["entries"] = kept

    if removed:
        _save(path, data)
    return removed
