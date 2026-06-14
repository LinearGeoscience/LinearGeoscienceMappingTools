#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Reconcile provenance: an append-only changelog beside the master.

One entry per accepted reconcile run records what was applied (insert/update/
delete counts and UUIDs), conflicts surfaced, the mapper, the batch id and a
monotonically increasing master_version. Mirrors MetadataManager's JSON-sidecar
style so the append history and the reconcile history read alike.

Pure module (no QGIS). File:
    <master_dir>/adddata_metadata/<master_stem>_lgs_changelog.json
"""

import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

try:  # package context
    from .checkout import metadata_folder, master_stem, atomic_write_json
    from .reconcile import ReconcilePlan
except ImportError:  # standalone (headless tests)
    from checkout import metadata_folder, master_stem, atomic_write_json
    from reconcile import ReconcilePlan

SCHEMA_VERSION = "1.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def changelog_path(master_gpkg: str) -> str:
    return os.path.join(metadata_folder(master_gpkg),
                        f"{master_stem(master_gpkg)}_lgs_changelog.json")


class ReconcileChangelog:
    """Append-only reconcile history for one master GeoPackage."""

    def __init__(self, master_gpkg: str):
        self.master_gpkg = master_gpkg
        self.path = changelog_path(master_gpkg)
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data.setdefault("entries", [])
                    return data
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "version": SCHEMA_VERSION,
            "created": _utc_now(),
            "last_updated": _utc_now(),
            "master_gpkg": os.path.basename(self.master_gpkg),
            "entries": [],
        }

    def save(self):
        self.data["last_updated"] = _utc_now()
        atomic_write_json(self.path, self.data)

    def current_version(self) -> int:
        """Master version = number of accepted reconcile/migration entries.

        Migration seeds entry 0; the first reconcile is version 1, etc.
        """
        return len(self.data["entries"])

    def append_entry(self, entry: dict) -> dict:
        entry.setdefault("timestamp_utc", _utc_now())
        entry["master_version"] = self.current_version() + 1
        self.data["entries"].append(entry)
        self.save()
        self._mirror_to_gpkg(entry)
        return entry

    def _mirror_to_gpkg(self, entry: dict):
        """Best-effort: mirror one entry into an `lgs_changelog` table inside
        the master GeoPackage so the history travels with the file. The JSON
        sidecar stays the source of truth; any failure here is swallowed.
        """
        if not os.path.exists(self.master_gpkg):
            return  # no real gpkg (e.g. headless tests) -> nothing to mirror
        con = None
        try:
            con = sqlite3.connect(self.master_gpkg, timeout=5)
            cur = con.cursor()
            cur.execute(
                "CREATE TABLE IF NOT EXISTS lgs_changelog ("
                "fid INTEGER PRIMARY KEY AUTOINCREMENT, master_version INTEGER, "
                "kind TEXT, batch_id TEXT, template_id TEXT, mapper TEXT, "
                "timestamp_utc TEXT, applied TEXT, notes TEXT)")
            cur.execute(
                "INSERT INTO lgs_changelog (master_version, kind, batch_id, "
                "template_id, mapper, timestamp_utc, applied, notes) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (entry.get("master_version"), entry.get("kind"),
                 entry.get("batch_id"), entry.get("template_id"),
                 entry.get("mapper"),
                 entry.get("timestamp_utc"),
                 json.dumps(entry.get("applied") or entry.get("summary") or {}),
                 entry.get("notes", "")))
            con.commit()   # persist the row before the optional registration
            # Register as an aspatial table so QGIS can open it (best-effort).
            try:
                stamp = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z")
                cur.execute(
                    "INSERT OR IGNORE INTO gpkg_contents "
                    "(table_name, data_type, identifier, description, "
                    "last_change) VALUES (?,?,?,?,?)",
                    ("lgs_changelog", "attributes", "lgs_changelog",
                     "Reconcile changelog", stamp))
                con.commit()
            except sqlite3.Error:
                pass
        except sqlite3.Error:
            pass
        finally:
            if con is not None:
                con.close()

    def log_migration(self, summary: dict) -> dict:
        return self.append_entry({
            "kind": "migration",
            "summary": summary,
        })

    def log_reconcile(self, batch_id: str, template_id: str, mapper: str,
                      plans: List[ReconcilePlan],
                      applied: Optional[dict] = None,
                      notes: str = "") -> dict:
        """Record one accepted reconcile across all its layers."""
        layers = []
        for plan in plans:
            layers.append({
                "layer": plan.layer,
                "summary": plan.summary(),
                "inserted_uuids": [o.uuid for o in plan.clean_inserts],
                "updated_uuids": [o.uuid for o in plan.clean_updates],
                "deleted_uuids": [o.uuid for o in plan.clean_deletes],
                "auto_merged_uuids": [o.uuid for o in plan.auto_merges],
                "conflicts": [c.to_dict() for c in plan.conflicts],
                "splits": [g.to_dict() for g in plan.splits
                           if hasattr(g, "to_dict")
                           and getattr(g, "accepted", True)],
                "merges": [g.to_dict() for g in plan.merges
                           if hasattr(g, "to_dict")
                           and getattr(g, "accepted", True)],
            })
        return self.append_entry({
            "kind": "reconcile",
            "batch_id": batch_id,
            "template_id": template_id,
            "mapper": mapper,
            "notes": notes,
            "applied": applied or {},
            "layers": layers,
        })

    def entries(self) -> list:
        return list(self.data["entries"])
