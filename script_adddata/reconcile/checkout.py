#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Checkout registry + base-snapshot store.

When a template is handed out (and after every accepted reconcile) we store a
per-(master, template) BASE snapshot: the common ancestor for the three-way
merge. The registry records who has which template out.

All artifacts live beside the master in the existing ``adddata_metadata``
folder, exactly like UUIDTracker / MetadataManager:
    <master_dir>/adddata_metadata/<master_stem>_checkouts.json
    <master_dir>/adddata_metadata/<master_stem>_<template_id>_base.json

Pure module (no QGIS). Capturing a template's features into LayerSnapshots is
done by the QGIS-bound engine, which then calls save_base() here.
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, Optional

try:  # package context
    from .snapshot import LayerSnapshot, FeatureFingerprint
except ImportError:  # standalone (headless tests)
    from snapshot import LayerSnapshot, FeatureFingerprint

SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
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
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def register(self, template_id: str, template_path: str, mapper: str,
                 master_version: int = 0, base_filename: str = "",
                 area_wkt: str = "") -> dict:
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

    def get(self, template_id: str) -> Optional[dict]:
        return self.data["checkouts"].get(template_id)

    def mark_reconciled(self, template_id: str, master_version: int = 0):
        entry = self.data["checkouts"].get(template_id)
        if entry:
            entry["status"] = self.STATUS_RECONCILED
            entry["last_sync_utc"] = _utc_now()
            entry["master_version"] = master_version
            self.save()

    def list(self) -> Dict[str, dict]:
        return dict(self.data["checkouts"])
