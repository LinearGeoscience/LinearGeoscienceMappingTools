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
4. Seed a master baseline snapshot (fingerprints of the current master) so the
   first reconcile of a legacy template has a reference, and record a
   migration entry (the lgs_migrated marker) in the changelog.

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
    from .snapshot import capture_layer, snapshot_from_payloads, is_empty
    from .checkout import metadata_folder, master_stem
    from .changelog import ReconcileChangelog
    from .commit import LGS_META_FIELDS
except ImportError:  # standalone
    from snapshot import capture_layer, snapshot_from_payloads, is_empty
    from checkout import metadata_folder, master_stem
    from changelog import ReconcileChangelog
    from commit import LGS_META_FIELDS

try:  # pragma: no cover - only inside QGIS
    from qgis.core import QgsVectorLayer, QgsField, QgsMessageLog, Qgis
    from qgis.PyQt.QtCore import QVariant
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

LGS_LAYERS = ['1 - FieldNotebook', '2 - Overlay', '3 - Linework', '4 - Basemap']
UUID_DEFAULT_EXPR = "uuid('WithoutBraces')"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open(master_gpkg: str, layer_name: str):
    lyr = QgsVectorLayer(f"{master_gpkg}|layername={layer_name}", layer_name, "ogr")
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
            fields.append(QgsField(name, QVariant.String))
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


def seed_master_baseline(master_gpkg: str, layer_names=None) -> str:
    """Capture current master fingerprints into <master>_master_baseline.json."""
    layer_names = layer_names or LGS_LAYERS
    layers = {}
    for name in layer_names:
        lyr = _open(master_gpkg, name)
        if lyr is None:
            continue
        uuid_field = "UUID"
        if detect_uuid_field:
            uuid_field = detect_uuid_field([f.name() for f in lyr.fields()]) or "UUID"
        payloads, _ = capture_layer(lyr, uuid_field=uuid_field, transform=None)
        layers[name] = snapshot_from_payloads(name, uuid_field, payloads).to_dict()

    data = {
        "version": "1.0", "schema": "lgs-snapshot",
        "master_gpkg": os.path.basename(master_gpkg),
        "template_id": "__master_baseline__",
        "captured_utc": _utc_now(),
        "master_version_at_capture": 0,
        "layers": layers,
    }
    path = os.path.join(metadata_folder(master_gpkg),
                        f"{master_stem(master_gpkg)}_master_baseline.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


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

    emit(90, "Seeding master baseline snapshot")
    try:
        report["baseline_path"] = seed_master_baseline(master_gpkg, layer_names)
    except Exception as exc:
        report["errors"].append(f"baseline: {exc}")

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
