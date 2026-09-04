#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
One-time, idempotent migration to prepare a master GeoPackage for reconcile
(QGIS-bound).

Steps (all safe to re-run):
1. Add the lgs_* provenance columns to the standard layers (provider-direct,
   no edit buffer) where missing.
2. Backfill any NULL/blank UUIDs with a fresh uuid4 (existing UUIDs are never
   changed); report duplicate UUIDs for attention.
3. Defensively verify each layer's QML carries the uuid('WithoutBraces')
   default on its UUID field, and inject it only if a layer is missing it
   (all four currently have it — normally a no-op).
4. Stamp a stable master_uid (basestore.ensure_master_uid) so working copies
   can prove which master they were issued from, and record a migration
   entry (the lgs_migrated marker) in the changelog.

`migration_status` is the pure (sqlite-only) preflight the dialogs use to
gate preview/apply/issue on an unmigrated master without opening layers.

QGIS imports are guarded so the module imports headlessly.
"""

import os
import re
import json
import sqlite3
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:  # package context
    from .snapshot import is_empty
    from .changelog import ReconcileChangelog, changelog_path
    from .commit import LGS_META_FIELDS
    from . import basestore
except ImportError:  # standalone
    from snapshot import is_empty
    from changelog import ReconcileChangelog, changelog_path
    from commit import LGS_META_FIELDS
    import basestore

try:  # pragma: no cover - only inside QGIS
    from qgis.core import QgsVectorLayer, QgsField, QgsMessageLog, Qgis
    from qgis.PyQt.QtCore import QMetaType
except Exception:  # pragma: no cover
    QgsVectorLayer = None
    QgsField = None

# create_compatible_field handles QGIS-version field construction; reuse it.
# hardcode_data lives at the plugin root: reconcile -> script_adddata -> root,
# hence three dots. detect_uuid_field is re-exported by analysis.
try:
    from ...hardcode_data.analysis import create_compatible_field, detect_uuid_field
except Exception:  # pragma: no cover
    try:
        from hardcode_data.analysis import create_compatible_field, detect_uuid_field
    except Exception:
        create_compatible_field = None
        detect_uuid_field = None

try:
    from ...lgs_layers import CANONICAL_LAYERS, gpkg_layer_name
except Exception:  # pragma: no cover
    from lgs_layers import CANONICAL_LAYERS, gpkg_layer_name

LGS_LAYERS = list(CANONICAL_LAYERS)
UUID_DEFAULT_EXPR = "uuid('WithoutBraces')"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open(master_gpkg: str, layer_name: str):
    lyr = QgsVectorLayer(f"{master_gpkg}|layername={layer_name}", layer_name, "ogr")
    if lyr.isValid():
        return lyr
    # Tolerate pre-Aug-2026 numbering (Linework/Overlay swapped) so an existing
    # master GeoPackage can still be registered for change tracking.
    actual = gpkg_layer_name(master_gpkg, layer_name)
    if not actual or actual == layer_name:
        return None
    lyr = QgsVectorLayer(f"{master_gpkg}|layername={actual}", actual, "ogr")
    return lyr if lyr.isValid() else None


def ensure_lgs_columns(layer) -> List[str]:
    """Add any missing lgs_* columns via the data provider. Returns names added."""
    existing = {f.name() for f in layer.fields()}
    to_add = [n for n in LGS_META_FIELDS if n not in existing]
    if not to_add:
        return []
    fields = []
    for name in to_add:
        if create_compatible_field is not None:
            fields.append(create_compatible_field(name, 'string'))
        else:  # pragma: no cover
            fields.append(QgsField(name, QMetaType.Type.QString))
    if layer.dataProvider().addAttributes(fields):
        layer.updateFields()
        return to_add
    return []


def backfill_uuids(layer, uuid_field: Optional[str] = None) -> dict:
    """Fill NULL/blank UUIDs with uuid4; report duplicates. Existing UUIDs kept."""
    report = {"uuid_field": uuid_field, "filled": 0, "duplicates": {}, "errors": []}
    names = [f.name() for f in layer.fields()]
    if uuid_field is None:
        uuid_field = detect_uuid_field(names) if detect_uuid_field else "UUID"
    report["uuid_field"] = uuid_field
    uidx = layer.fields().indexOf(uuid_field)
    if uidx == -1:
        report["errors"].append(f"no UUID field on {layer.name()}")
        return report

    seen: Dict[str, List[int]] = {}
    to_fill: Dict[int, str] = {}
    for feat in layer.getFeatures():
        val = feat.attribute(uidx)
        if is_empty(val):
            to_fill[feat.id()] = str(uuid_module.uuid4())
        else:
            seen.setdefault(str(val).strip(), []).append(feat.id())

    report["duplicates"] = {v: fids for v, fids in seen.items() if len(fids) > 1}

    if to_fill:
        if not layer.isEditable() and not layer.startEditing():
            report["errors"].append(f"could not edit {layer.name()}")
            return report
        try:
            for fid, val in to_fill.items():
                layer.changeAttributeValue(fid, uidx, val)
            if layer.commitChanges():
                report["filled"] = len(to_fill)
            else:
                report["errors"].extend(str(e) for e in layer.commitErrors())
                layer.rollBack()
        except Exception as exc:  # pragma: no cover
            layer.rollBack()
            report["errors"].append(str(exc))
    return report


def _uuid_field_of(qml: str) -> Optional[str]:
    """Find the UUID field's <default> block in a styleQML (order-agnostic)."""
    for m in re.finditer(r'<default\b[^>]*>', qml):
        tag = m.group(0)
        fm = re.search(r'field="([^"]*)"', tag)
        if fm and fm.group(1).lower() == "uuid":
            return tag
    return None


def verify_uuid_defaults(master_gpkg: str) -> dict:
    """Check (and only if missing, inject) the UUID default expression per layer.

    Returns {layer: 'ok' | 'patched' | 'no-style' | 'no-uuid-field' | error}.
    """
    out: Dict[str, str] = {}
    try:
        con = sqlite3.connect(master_gpkg)
    except Exception as exc:  # pragma: no cover
        return {"_error": str(exc)}
    try:
        cur = con.cursor()
        # layer_styles may not exist on a brand-new gpkg.
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='layer_styles'")
        if not cur.fetchone():
            return {L: "no-style" for L in LGS_LAYERS}

        for layer in LGS_LAYERS:
            cur.execute("SELECT rowid, styleQML FROM layer_styles "
                        "WHERE f_table_name=? ORDER BY rowid", (layer,))
            row = cur.fetchone()
            if not row:
                out[layer] = "no-style"
                continue
            rowid, qml = row
            qml = qml or ""
            tag = _uuid_field_of(qml)
            if tag is None:
                out[layer] = "no-uuid-field"
                continue
            if "uuid(" in tag.lower():
                out[layer] = "ok"
                continue
            # Inject the default expression into the existing UUID <default> tag.
            new_tag = re.sub(r'expression="[^"]*"',
                             f'expression="{UUID_DEFAULT_EXPR}"', tag)
            if new_tag == tag:  # tag had no expression attribute
                new_tag = tag[:-2] + f' expression="{UUID_DEFAULT_EXPR}"/>' \
                    if tag.endswith("/>") else tag
            new_qml = qml.replace(tag, new_tag, 1)
            cur.execute("UPDATE layer_styles SET styleQML=? WHERE rowid=?",
                        (new_qml, rowid))
            con.commit()
            out[layer] = "patched"
        return out
    finally:
        con.close()


def migration_status(master_gpkg: str, layer_names=None) -> dict:
    """Pure (sqlite-only) preflight: has this master been migrated?

    Cheap enough to run on every master pick — PRAGMA table_info per layer,
    no QGIS, no feature scans. A master counts as migrated when every
    canonical layer present in the file has the lgs_* columns and a UUID
    column, and a migration marker exists (lgs_changelog table row or the
    JSON changelog sidecar).

    Returns {"migrated": bool, "layers": {name: {"present", "has_lgs_columns",
    "has_uuid"}}, "has_migration_marker": bool, "master_uid": str|None,
    "error": str (only on failure to open)}.
    """
    layer_names = layer_names or LGS_LAYERS
    out = {"migrated": False, "layers": {}, "has_migration_marker": False,
           "master_uid": None}
    if not os.path.exists(master_gpkg):
        out["error"] = "file not found"
        return out
    try:
        con = sqlite3.connect(master_gpkg, timeout=5)
    except sqlite3.Error as exc:
        out["error"] = str(exc)
        return out
    try:
        cur = con.cursor()
        layers_ok = True
        any_present = False
        for name in layer_names:
            actual = gpkg_layer_name(master_gpkg, name)
            info = {"present": actual is not None,
                    "has_lgs_columns": False, "has_uuid": False}
            if actual:
                any_present = True
                # Table names may contain spaces/dashes: quote them.
                cur.execute(f'PRAGMA table_info("{actual}")')
                cols = {row[1] for row in cur.fetchall()}
                info["has_lgs_columns"] = all(
                    f in cols for f in LGS_META_FIELDS)
                if detect_uuid_field:
                    info["has_uuid"] = bool(detect_uuid_field(sorted(cols)))
                else:  # pragma: no cover - headless fallback
                    info["has_uuid"] = any("uuid" in c.lower() for c in cols)
                if not (info["has_lgs_columns"] and info["has_uuid"]):
                    layers_ok = False
            out["layers"][name] = info

        # Migration marker: the mirrored table, or the JSON sidecar.
        try:
            cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='lgs_changelog'")
            if cur.fetchone():
                cur.execute("SELECT 1 FROM lgs_changelog "
                            "WHERE kind='migration' LIMIT 1")
                out["has_migration_marker"] = cur.fetchone() is not None
        except sqlite3.Error:
            pass
        if not out["has_migration_marker"]:
            try:
                path = changelog_path(master_gpkg)
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        entries = (json.load(f) or {}).get("entries", [])
                    out["has_migration_marker"] = any(
                        e.get("kind") == "migration" for e in entries)
            except (json.JSONDecodeError, IOError):
                pass

        out["master_uid"] = basestore.read_master_uid(master_gpkg)
        out["migrated"] = bool(any_present and layers_ok
                               and out["has_migration_marker"])
        return out
    finally:
        con.close()


def run_migration(master_gpkg: str, layer_names=None, progress_cb=None) -> dict:
    """Run the full idempotent migration. Returns a report dict."""
    if QgsVectorLayer is None:
        return {"ok": False, "errors": ["QGIS not available"]}
    layer_names = layer_names or LGS_LAYERS
    report = {"ok": False, "master_gpkg": master_gpkg, "layers": {},
              "uuid_defaults": {}, "errors": []}

    def emit(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    for i, name in enumerate(layer_names):
        emit(int(i / max(len(layer_names), 1) * 70), f"Migrating {name}")
        lyr = _open(master_gpkg, name)
        if lyr is None:
            report["layers"][name] = {"present": False}
            continue
        added = ensure_lgs_columns(lyr)
        bf = backfill_uuids(lyr)
        report["layers"][name] = {
            "present": True, "columns_added": added,
            "uuids_filled": bf["filled"],
            "duplicate_uuids": list(bf["duplicates"].keys()),
            "errors": bf["errors"],
        }
        if bf["errors"]:
            report["errors"].extend(bf["errors"])

    emit(80, "Verifying UUID defaults")
    report["uuid_defaults"] = verify_uuid_defaults(master_gpkg)

    emit(90, "Stamping master identity")
    report["master_uid"] = basestore.ensure_master_uid(master_gpkg)
    if not report["master_uid"]:
        # Best-effort: pairing guard falls back to basename matching.
        report["errors"].append("could not stamp master_uid (file locked?)")

    emit(95, "Recording migration")
    try:
        ReconcileChangelog(master_gpkg).log_migration({
            "lgs_migrated": True,
            "layers": {n: v for n, v in report["layers"].items()},
            "uuid_defaults": report["uuid_defaults"],
        })
    except Exception as exc:
        report["errors"].append(f"changelog: {exc}")

    emit(100, "Migration complete")
    report["ok"] = not report["errors"]
    return report
