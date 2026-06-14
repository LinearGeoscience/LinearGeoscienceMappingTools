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
from datetime import datetime, timezone
from typing import List, Optional

try:  # package context
    from .checkout import metadata_folder, master_stem
    from .reconcile import ReconcilePlan
except ImportError:  # standalone (headless tests)
    from checkout import metadata_folder, master_stem
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
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

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
        return entry

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
                "conflicts": [c.to_dict() for c in plan.conflicts],
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
