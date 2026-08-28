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
    from .snapshot import is_empty
except ImportError:  # standalone
    from reconcile import ReconcilePlan, Op, OP_INSERT, OP_UPDATE, OP_DELETE
    from snapshot import is_empty

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
              "errors": [], "tombstones": [], "layer": plan.layer}

    if QgsFeature is None:
        result["errors"].append("QGIS not available")
        return result

    # applicable_ops folds clean ops + auto-merges + resolved conflicts into a
    # single insert/update/delete set, after the chosen resolutions.
    inserts, updates, deletes = plan.applicable_ops()
    if not (inserts or updates or deletes):
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
        for op in inserts:
            feat = QgsFeature(fields)
            _apply_payload_attrs(master_layer, feat, op, uuid_field)
            _set_if_present(master_layer, feat, uuid_field, op.uuid)
            _set_if_present(master_layer, feat, LGS_VERSION, "1")
            _set_if_present(master_layer, feat, LGS_LAST_MODIFIED, ts)
            _set_if_present(master_layer, feat, LGS_AUTHOR, mapper)
            _set_if_present(master_layer, feat, LGS_EDITOR, mapper)
            _set_if_present(master_layer, feat, LGS_FEATURE_HASH,
                            op.payload.fingerprint().attr_hash if op.payload else "")
            if op.lgs_parent_uuid:
                _set_if_present(master_layer, feat, LGS_PARENT_UUID,
                                op.lgs_parent_uuid)
            if op.lgs_merged_from:
                _set_if_present(master_layer, feat, LGS_MERGED_FROM,
                                op.lgs_merged_from)
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

        # ---- updates (clean updates + auto-merges + resolved conflicts) ----
        for op in updates:
            fid = uuid_to_fid.get(op.uuid)
            if fid is None:
                result["errors"].append(f"update target {op.uuid} not found")
                continue
            err = _apply_update(master_layer, fid, op, mapper, ts, uuid_field)
            if err:
                result["errors"].append(err)
            else:
                result["updated"] += 1

        # ---- deletes (record a tombstone before removing) ----
        for op in deletes:
            fid = uuid_to_fid.get(op.uuid)
            if fid is None:
                continue
            rec = _tombstone_record(master_layer, fid, op.uuid, plan.layer,
                                    batch_id, mapper, ts)
            if master_layer.deleteFeature(fid):
                result["deleted"] += 1
                if rec is not None:
                    result["tombstones"].append(rec)
            else:
                result["errors"].append(f"delete failed for {op.uuid}")

        if master_layer.commitChanges():
            master_layer.updateExtents()
            master_layer.triggerRepaint()
            result["ok"] = True
            return result

        result["errors"].extend(str(e) for e in master_layer.commitErrors())
        master_layer.rollBack()
        result["tombstones"] = []   # rolled back -> nothing was actually deleted
        return result

    except Exception as exc:  # pragma: no cover - defensive
        master_layer.rollBack()
        result["tombstones"] = []
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
    """Apply one update by fid: changed attrs + geometry + provenance bump.

    Returns None on success, or an error string if a buffered change was
    rejected (so the caller does not over-count and the layer rolls back).
    """
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
    if op.lgs_parent_uuid:
        put(LGS_PARENT_UUID, op.lgs_parent_uuid)
    if op.lgs_merged_from:
        put(LGS_MERGED_FROM, op.lgs_merged_from)

    if changes:
        if not master_layer.changeAttributeValues(fid, changes):
            return f"attribute update rejected for {op.uuid}"

    if op.geom_changed and payload and payload.wkb:
        geom = QgsGeometry()
        geom.fromWkb(payload.wkb)
        if not master_layer.changeGeometry(fid, geom):
            return f"geometry update rejected for {op.uuid}"
    return None


def _json_value(value):
    """Coerce an attribute value to something JSON-serialisable for a tombstone."""
    if is_empty(value):
        return None
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _tombstone_record(layer, fid, uuid, layer_name, batch_id, mapper, ts):
    """Snapshot a feature's attrs + geometry (WKB hex) just before deletion."""
    try:
        feat = layer.getFeature(fid)
    except Exception:  # pragma: no cover - defensive
        return None
    attrs = {}
    fields = layer.fields()
    vals = feat.attributes()
    for i in range(len(fields)):
        name = fields[i].name()
        if name.lower() == "fid":
            continue
        attrs[name] = _json_value(vals[i] if i < len(vals) else None)
    wkb_hex = None
    try:
        if feat.hasGeometry():
            g = feat.geometry()
            if g is not None and not g.isNull() and not g.isEmpty():
                wkb_hex = bytes(g.asWkb()).hex()
    except Exception:  # pragma: no cover
        pass
    return {"uuid": uuid, "layer": layer_name, "batch_id": batch_id,
            "mapper": mapper, "deleted_utc": ts, "attrs": attrs,
            "wkb_hex": wkb_hex}
