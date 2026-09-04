#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Checkout registry + LEGACY sidecar base-snapshot store.

The registry records who has which working copy out and whether it has been
merged back. Entries are keyed by ``checkout_id`` (the uuid stamped inside
the working copy by basestore.write_checkout) for embedded checkouts, or by
the filename-stem ``template_id`` for legacy sidecar-era entries; both kinds
coexist in one file.

The base-snapshot JSON sidecar functions below are the LEGACY store: the
primary ancestor now lives inside the working copy itself (see basestore.py).
They are kept for (a) reading bases recorded before the embedded store
existed and (b) the apply-time recovery mirror - engine.apply_plans writes
the advanced base to BOTH stores, so if the working file is locked at
refresh time the sidecar still carries the truth (newest capture wins on
the next build, basestore.newest_base).

All sidecar artifacts live beside the master in the existing
``adddata_metadata`` folder, exactly like UUIDTracker / MetadataManager:
    <master_dir>/adddata_metadata/<master_stem>_checkouts.json
    <master_dir>/adddata_metadata/<master_stem>_<template_id>_base.json

Pure module (no QGIS). Capturing a template's features into LayerSnapshots is
done by the QGIS-bound engine, which then calls save_base() here.
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:  # package context
    from .snapshot import LayerSnapshot, FeatureFingerprint
except ImportError:  # standalone (headless tests)
    from snapshot import LayerSnapshot, FeatureFingerprint

SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: str, data: dict):
    """Write JSON via a temp file + os.replace so a crash mid-write can't leave
    a truncated/corrupt artifact (the base snapshot and registry are critical).
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def metadata_folder(master_gpkg: str) -> str:
    """Return (creating if needed) the adddata_metadata folder for a master.

    Falls back to the master's own directory if the folder can't be created,
    matching MetadataManager._get_metadata_folder.
    """
    master_dir = os.path.dirname(master_gpkg)
    folder = os.path.join(master_dir, "adddata_metadata")
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except OSError:
            return master_dir
    return folder


def master_stem(master_gpkg: str) -> str:
    return os.path.splitext(os.path.basename(master_gpkg))[0]


def template_id_from_path(template_path: str) -> str:
    """A template's id is its gpkg filename stem (e.g. LGS_SiteA_28350)."""
    return os.path.splitext(os.path.basename(template_path))[0]


def _artifact_path(master_gpkg: str, suffix: str) -> str:
    return os.path.join(metadata_folder(master_gpkg),
                        f"{master_stem(master_gpkg)}_{suffix}")


def base_path(master_gpkg: str, template_id: str) -> str:
    return _artifact_path(master_gpkg, f"{template_id}_base.json")


def checkouts_path(master_gpkg: str) -> str:
    return _artifact_path(master_gpkg, "checkouts.json")


# --------------------------------------------------------------------------
# Base snapshot store
# --------------------------------------------------------------------------

def save_base(master_gpkg: str, template_id: str,
              layers: Dict[str, LayerSnapshot],
              master_version: int = 0, mapper: str = "",
              captured_utc: Optional[str] = None) -> str:
    """Write the base snapshot for a (master, template) pair. Returns path."""
    data = {
        "version": SCHEMA_VERSION,
        "schema": "lgs-snapshot",
        "master_gpkg": os.path.basename(master_gpkg),
        "template_id": template_id,
        "captured_utc": captured_utc or _utc_now(),
        "master_version_at_capture": master_version,
        "mapper": mapper,
        "layers": {name: snap.to_dict() for name, snap in layers.items()},
    }
    path = base_path(master_gpkg, template_id)
    atomic_write_json(path, data)
    return path


def load_base(master_gpkg: str, template_id: str) -> Optional[dict]:
    """Load a base snapshot.

    Returns a dict with keys 'master_version_at_capture', 'captured_utc',
    'mapper' and 'layers' = {layer_name: {uuid: FeatureFingerprint}}.
    Returns None if no base has been recorded (legacy first sync).
    """
    path = base_path(master_gpkg, template_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
    layers = {}
    for name, d in (raw.get("layers") or {}).items():
        snap = LayerSnapshot.from_dict(name, d)
        layers[name] = snap.features
    return {
        "master_version_at_capture": raw.get("master_version_at_capture", 0),
        "captured_utc": raw.get("captured_utc"),
        "mapper": raw.get("mapper", ""),
        "layers": layers,
    }


def load_base_layer(master_gpkg: str, template_id: str,
                    layer_name: str) -> Optional[Dict[str, FeatureFingerprint]]:
    """Convenience: the {uuid: fingerprint} base for one layer, or None.

    None means "no base recorded at all" (caller should synthesize). An empty
    dict means "base recorded but this layer was empty".
    """
    base = load_base(master_gpkg, template_id)
    if base is None:
        return None
    return base["layers"].get(layer_name, {})


def update_base(master_gpkg: str, template_id: str,
                layers: Dict[str, LayerSnapshot],
                master_version: int = 0, mapper: str = "") -> str:
    """Advance the base after an accepted reconcile (same as save_base).

    This is the re-append fix: the just-synced working state becomes the new
    common ancestor, so the next sync sees further edits as updates rather
    than silently-skipped duplicates.
    """
    return save_base(master_gpkg, template_id, layers, master_version, mapper)


# --------------------------------------------------------------------------
# Checkout registry
# --------------------------------------------------------------------------

class CheckoutRegistry:
    """Tracks which templates are out, who has them, and their base."""

    STATUS_OUT = "out"
    STATUS_RECONCILED = "reconciled"

    def __init__(self, master_gpkg: str):
        self.master_gpkg = master_gpkg
        self.path = checkouts_path(master_gpkg)
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data.setdefault("checkouts", {})
                    return data
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "version": SCHEMA_VERSION,
            "created": _utc_now(),
            "last_updated": _utc_now(),
            "master_gpkg": os.path.basename(self.master_gpkg),
            "checkouts": {},
        }

    def save(self):
        self.data["last_updated"] = _utc_now()
        atomic_write_json(self.path, self.data)

    def register(self, template_id: str, template_path: str, mapper: str,
                 master_version: int = 0, base_filename: str = "",
                 area_wkt: str = "") -> dict:
        """LEGACY registration keyed by filename-stem template_id.

        Kept for sidecar-era callers; overwrites an existing entry with the
        same stem (the flaw that motivated checkout_id keying). New code
        should stamp via basestore + register_checkout instead.
        """
        entry = {
            "template_id": template_id,
            "template_path": template_path,
            "mapper": mapper,
            "area_wkt": area_wkt,
            "master_version": master_version,
            "base_snapshot": base_filename or os.path.basename(
                base_path(self.master_gpkg, template_id)),
            "created_utc": _utc_now(),
            "last_sync_utc": None,
            "status": self.STATUS_OUT,
        }
        self.data["checkouts"][template_id] = entry
        self.save()
        return entry

    def register_checkout(self, entry: dict) -> dict:
        """Register an embedded checkout, keyed by its checkout_id (uuid) -
        collisions are impossible, so nothing can be silently clobbered.

        ``entry`` must carry checkout_id; template_id/template_path/mapper/
        source_mode/area_wkt/master_version are stored as given. Re-registering
        the same checkout_id (e.g. a re-stamp) replaces its own entry only.
        """
        checkout_id = entry["checkout_id"]
        stored = {
            "checkout_id": checkout_id,
            "template_id": entry.get("template_id", ""),
            "template_path": entry.get("template_path", ""),
            "mapper": entry.get("mapper", ""),
            "source_mode": entry.get("source_mode", ""),
            "area_wkt": entry.get("area_wkt", ""),
            "master_version": entry.get("master_version", 0),
            "base": "embedded",
            "created_utc": entry.get("issued_utc") or _utc_now(),
            "last_sync_utc": None,
            "status": self.STATUS_OUT,
        }
        self.data["checkouts"][checkout_id] = stored
        self.save()
        return stored

    def get(self, key: str) -> Optional[dict]:
        """Look up by checkout_id or legacy template_id (both are keys)."""
        return self.data["checkouts"].get(key)

    def mark_reconciled(self, key: str, master_version: int = 0,
                        mapper: str = ""):
        """Mark an entry merged. ``key`` is a checkout_id or a legacy
        template_id. A non-empty ``mapper`` backfills a blank one (export-time
        stamps don't know the mapper yet; the first reconcile does)."""
        entry = self.data["checkouts"].get(key)
        if entry:
            entry["status"] = self.STATUS_RECONCILED
            entry["last_sync_utc"] = _utc_now()
            entry["master_version"] = master_version
            if mapper and not entry.get("mapper"):
                entry["mapper"] = mapper
            self.save()

    def list(self) -> Dict[str, dict]:
        return dict(self.data["checkouts"])

    def entries(self) -> List[dict]:
        """Normalized rows for the dashboard: every entry gains a ``key``
        (its dict key) and a ``base`` kind ("embedded" | "sidecar"), sorted
        newest-issued first so current hand-outs top the list."""
        rows = []
        for key, entry in self.data["checkouts"].items():
            row = dict(entry)
            row["key"] = key
            row.setdefault("base", "sidecar")
            row.setdefault("source_mode", "legacy")
            rows.append(row)
        rows.sort(key=lambda r: r.get("created_utc") or "", reverse=True)
        return rows


def _short_date(ts) -> str:
    """'2026-09-04T07:11:22+00:00' -> '2026-09-04'; tolerant of blanks."""
    return (ts or "")[:10] or "—"


def describe_entry(entry: dict) -> dict:
    """Display row for one registry entry (pure; used by the dashboard).

    Returns display strings plus a ``file_state`` in
    {"ok", "moved", "restamped", "unknown"} — "restamped" means the file at
    the recorded path carries a DIFFERENT checkout_id now (e.g. it was
    re-issued under the same name), so this entry is historical.
    """
    try:  # lazy: only needed when the entry has a live file to probe
        from . import basestore
    except ImportError:  # standalone (headless tests)
        import basestore

    path = entry.get("template_path") or ""
    row = {
        "name": entry.get("template_id") or os.path.basename(path)
                or entry.get("key", ""),
        "mapper": entry.get("mapper") or "—",
        "issued": _short_date(entry.get("created_utc")),
        "source": entry.get("source_mode") or "legacy",
        "last_sync": _short_date(entry.get("last_sync_utc")),
        "status": entry.get("status") or "?",
        "base": entry.get("base") or "sidecar",
        "path": path,
        "file_state": "unknown",
    }
    if path:
        if not os.path.exists(path):
            row["file_state"] = "moved"
        elif entry.get("checkout_id"):
            try:
                ck = basestore.read_checkout(path)
                row["file_state"] = (
                    "ok" if ck and ck.get("checkout_id") ==
                    entry["checkout_id"] else "restamped")
            except Exception:
                row["file_state"] = "unknown"
        else:
            row["file_state"] = "ok"
    return row
