#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Transactional apply of a ReconcilePlan to the master layer (QGIS-bound).

Applies clean inserts / updates / deletes for one layer inside a single
QgsVectorLayer edit session: on any error the whole layer's changes roll back
(the same commitChanges()/rollBack() pattern as
hardcode_data.analysis.apply_layer_report). Conflicts and lineage groups are
never applied here — only the clean ops the plan marked applicable.

Every applied feature is stamped with lgs_* provenance:
- insert: lgs_version=1, lgs_author=mapper, lgs_editor=mapper
- update: lgs_version bumped, lgs_editor=mapper
plus lgs_last_modified (UTC) and lgs_feature_hash (content fingerprint). New
features also get data_added_timestamp / data_added_batch_id where those
columns exist, matching the append tool.

QGIS imports are guarded so the module imports (but does not run) headlessly.
"""

from datetime import datetime, timezone
from typing import Dict, Optional

try:  # package context
    from .reconcile import ReconcilePlan, Op, OP_INSERT, OP_UPDATE, OP_DELETE
except ImportError:  # standalone
    from reconcile import ReconcilePlan, Op, OP_INSERT, OP_UPDATE, OP_DELETE

try:  # pragma: no cover - only inside QGIS
    from qgis.core import QgsFeature, QgsGeometry
except Exception:  # pragma: no cover
    QgsFeature = None
    QgsGeometry = None


# lgs_* provenance columns maintained by reconcile.
LGS_VERSION = "lgs_version"
LGS_LAST_MODIFIED = "lgs_last_modified"
LGS_AUTHOR = "lgs_author"
LGS_EDITOR = "lgs_editor"
LGS_FEATURE_HASH = "lgs_feature_hash"
LGS_PARENT_UUID = "lgs_parent_uuid"
LGS_MERGED_FROM = "lgs_merged_from"
LGS_META_FIELDS = [LGS_VERSION, LGS_LAST_MODIFIED, LGS_AUTHOR, LGS_EDITOR,
                   LGS_FEATURE_HASH, LGS_PARENT_UUID, LGS_MERGED_FROM]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_field(layer, name: str) -> bool:
    return layer.fields().indexOf(name) != -1


def _set_if_present(layer, feat, name, value):
    idx = layer.fields().indexOf(name)
    if idx != -1:
        feat.setAttribute(idx, value)


def _build_uuid_index(layer, uuid_field: str) -> Dict[str, int]:
    """Map current master UUID -> fid (first wins)."""
    out: Dict[str, int] = {}
    uidx = layer.fields().indexOf(uuid_field)
    if uidx == -1:
        return out
    for feat in layer.getFeatures():
        val = feat.attribute(uidx)
        if val is None:
            continue
        key = str(val).strip()
        if key and key not in out:
            out[key] = feat.id()
    return out


def apply_plan(master_layer, plan: ReconcilePlan, mapper: str = "",
               batch_id: str = "", uuid_field: str = "UUID",
               timestamp: Optional[str] = None) -> dict:
    """Apply a plan's clean ops to one master layer in a single transaction.

    Returns {ok, inserted, updated, deleted, errors:[...]}.
    """
    result = {"ok": False, "inserted": 0, "updated": 0, "deleted": 0,
              "errors": [], "layer": plan.layer}

    if QgsFeature is None:
        result["errors"].append("QGIS not available")
        return result

    if not plan.has_applicable_changes():
        result["ok"] = True
        return result

    ts = timestamp or _utc_now()

    if not master_layer.isEditable() and not master_layer.startEditing():
        result["errors"].append(f"Could not start editing '{plan.layer}'")
        return result

    try:
        fields = master_layer.fields()
        uuid_to_fid = _build_uuid_index(master_layer, uuid_field)
        has_added_ts = _has_field(master_layer, "data_added_timestamp")
        has_added_batch = _has_field(master_layer, "data_added_batch_id")

        # ---- inserts ----
        for op in plan.clean_inserts:
            feat = QgsFeature(fields)
            _apply_payload_attrs(master_layer, feat, op, uuid_field)
            _set_if_present(master_layer, feat, uuid_field, op.uuid)
            _set_if_present(master_layer, feat, LGS_VERSION, "1")
            _set_if_present(master_layer, feat, LGS_LAST_MODIFIED, ts)
            _set_if_present(master_layer, feat, LGS_AUTHOR, mapper)
            _set_if_present(master_layer, feat, LGS_EDITOR, mapper)
            _set_if_present(master_layer, feat, LGS_FEATURE_HASH,
                            op.payload.fingerprint().attr_hash if op.payload else "")
            if has_added_ts:
                _set_if_present(master_layer, feat, "data_added_timestamp", ts)
            if has_added_batch:
                _set_if_present(master_layer, feat, "data_added_batch_id", batch_id)
            if op.payload and op.payload.wkb:
                geom = QgsGeometry()
                geom.fromWkb(op.payload.wkb)
                feat.setGeometry(geom)
            if master_layer.addFeature(feat):
                result["inserted"] += 1
            else:
                result["errors"].append(f"insert failed for {op.uuid}")

        # ---- updates ----
        for op in plan.clean_updates:
            fid = uuid_to_fid.get(op.uuid)
            if fid is None:
                result["errors"].append(f"update target {op.uuid} not found")
                continue
            _apply_update(master_layer, fid, op, mapper, ts, uuid_field)
            result["updated"] += 1

        # ---- deletes ----
        for op in plan.clean_deletes:
            fid = uuid_to_fid.get(op.uuid)
            if fid is None:
                continue
            if master_layer.deleteFeature(fid):
                result["deleted"] += 1
            else:
                result["errors"].append(f"delete failed for {op.uuid}")

        if master_layer.commitChanges():
            master_layer.updateExtents()
            master_layer.triggerRepaint()
            result["ok"] = True
            return result

        result["errors"].extend(str(e) for e in master_layer.commitErrors())
        master_layer.rollBack()
        return result

    except Exception as exc:  # pragma: no cover - defensive
        master_layer.rollBack()
        result["errors"].append(str(exc))
        return result


def _apply_payload_attrs(master_layer, feat, op: Op, uuid_field: str):
    """Copy working payload attributes onto a new feature (matching names)."""
    if not op.payload:
        return
    for name, value in op.payload.attrs.items():
        if name == op.payload.geom_field or name.lower() == "fid":
            continue
        if name in LGS_META_FIELDS:
            continue  # provenance set explicitly
        _set_if_present(master_layer, feat, name, value)


def _apply_update(master_layer, fid, op: Op, mapper: str, ts: str,
                  uuid_field: str):
    """Apply one update by fid: changed attrs + geometry + provenance bump."""
    fields = master_layer.fields()
    payload = op.payload

    # Current lgs_version -> bump.
    new_version = "1"
    vidx = fields.indexOf(LGS_VERSION)
    if vidx != -1:
        cur = master_layer.getFeature(fid).attribute(vidx)
        try:
            new_version = str(int(str(cur)) + 1) if cur not in (None, "") else "1"
        except (ValueError, TypeError):
            new_version = "1"

    changes = {}
    if payload:
        for name, value in payload.attrs.items():
            if name == payload.geom_field or name.lower() == "fid":
                continue
            if name in LGS_META_FIELDS or name == uuid_field:
                continue
            idx = fields.indexOf(name)
            if idx != -1:
                changes[idx] = value

    def put(name, value):
        idx = fields.indexOf(name)
        if idx != -1:
            changes[idx] = value

    put(LGS_VERSION, new_version)
    put(LGS_LAST_MODIFIED, ts)
    put(LGS_EDITOR, mapper)
    put(LGS_FEATURE_HASH, payload.fingerprint().attr_hash if payload else "")

    if changes:
        master_layer.changeAttributeValues(fid, changes)

    if op.geom_changed and payload and payload.wkb:
        geom = QgsGeometry()
        geom.fromWkb(payload.wkb)
        master_layer.changeGeometry(fid, geom)
