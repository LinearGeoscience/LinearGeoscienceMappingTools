#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Reconcile orchestrator (QGIS-bound): ties capture -> classify -> commit ->
advance-base -> changelog, and provides the checkout hook used when a template
is handed out.

This is the only place the GUI/worker needs to call:
- build_plans(master, template)   -> plans + working captures (for preview)
- apply_plans(...)                -> commit accepted clean ops, advance base,
                                     mark the checkout reconciled, log it
- register_and_snapshot(...)      -> record a handout + store its base snapshot

Identity is UUID throughout; geometry is hashed in the MASTER CRS (working
geometry is transformed at capture) so base/working/master are comparable.

QGIS imports are guarded so the module imports headlessly.
"""

import uuid as uuid_module
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:  # package context
    from . import checkout
    from .snapshot import capture_layer, snapshot_from_payloads, FeatureFingerprint
    from .reconcile import classify, ReconcilePlan
    from .changelog import ReconcileChangelog
    from . import commit as commit_mod
    from .migrate import LGS_LAYERS
except ImportError:  # standalone
    import checkout
    from snapshot import capture_layer, snapshot_from_payloads, FeatureFingerprint
    from reconcile import classify, ReconcilePlan
    from changelog import ReconcileChangelog
    import commit as commit_mod
    from migrate import LGS_LAYERS

try:  # pragma: no cover - only inside QGIS
    from qgis.core import (QgsVectorLayer, QgsCoordinateTransform, QgsProject)
except Exception:  # pragma: no cover
    QgsVectorLayer = None

try:
    from ..utils import detect_uuid_field
except Exception:  # pragma: no cover
    try:
        from script_adddata.utils import detect_uuid_field
    except Exception:
        detect_uuid_field = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_batch_id() -> str:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    return f"reconcile_{stamp}_{uuid_module.uuid4().hex[:8]}"


def _open(gpkg: str, layer_name: str):
    lyr = QgsVectorLayer(f"{gpkg}|layername={layer_name}", layer_name, "ogr")
    return lyr if lyr.isValid() else None


def _uuid_field(layer, default: str = "UUID") -> str:
    names = [f.name() for f in layer.fields()]
    if detect_uuid_field:
        return detect_uuid_field(names) or default
    return default if default in names else (names[0] if names else default)


def _transform(src_layer, dst_layer):
    try:
        scrs, dcrs = src_layer.crs(), dst_layer.crs()
        if scrs.isValid() and dcrs.isValid() and scrs != dcrs:
            return QgsCoordinateTransform(scrs, dcrs, QgsProject.instance())
    except Exception:
        pass
    return None


def _master_fingerprints(master_layer, uuid_field) -> Dict[str, FeatureFingerprint]:
    payloads, _ = capture_layer(master_layer, uuid_field=uuid_field, transform=None)
    return {u: p.fingerprint() for u, p in payloads.items()}


def build_plans(master_gpkg: str, template_path: str,
                layer_names: Optional[List[str]] = None,
                progress_cb=None) -> dict:
    """Capture + classify every standard layer. Does NOT modify anything.

    Returns {plans: [ReconcilePlan], captures: {layer: working_payloads},
    reports: {layer: capture_report}, template_id, missing_layers, errors}.
    """
    layer_names = layer_names or LGS_LAYERS
    template_id = checkout.template_id_from_path(template_path)
    out = {"template_id": template_id, "plans": [], "captures": {},
           "reports": {}, "uuid_fields": {}, "missing_layers": [], "errors": []}

    if QgsVectorLayer is None:
        out["errors"].append("QGIS not available")
        return out

    for i, name in enumerate(layer_names):
        if progress_cb:
            progress_cb(int(i / max(len(layer_names), 1) * 100), f"Reading {name}")

        tpl_layer = _open(template_path, name)
        if tpl_layer is None:
            continue  # template doesn't have this layer; nothing to sync
        master_layer = _open(master_gpkg, name)
        if master_layer is None:
            # Reconcile MVP requires the master layer to exist. Surface it.
            out["missing_layers"].append(name)
            continue

        uuid_field = _uuid_field(tpl_layer)
        master_uuid_field = _uuid_field(master_layer)
        transform = _transform(tpl_layer, master_layer)

        working_payloads, wreport = capture_layer(
            tpl_layer, uuid_field=uuid_field, transform=transform)
        master_fp = _master_fingerprints(master_layer, master_uuid_field)
        base_fp = checkout.load_base_layer(master_gpkg, template_id, name)

        plan = classify(name, uuid_field, base_fp, working_payloads, master_fp)
        out["plans"].append(plan)
        out["captures"][name] = working_payloads
        out["reports"][name] = wreport
        out["uuid_fields"][name] = uuid_field

    return out


def apply_plans(master_gpkg: str, template_path: str, build: dict,
                mapper: str = "", batch_id: Optional[str] = None,
                progress_cb=None) -> dict:
    """Commit the clean ops of each plan, then advance base + log.

    `build` is the dict returned by build_plans (possibly with conflicts left
    unresolved — those are simply not applied in the MVP).
    """
    template_id = build["template_id"]
    plans: List[ReconcilePlan] = build["plans"]
    captures = build["captures"]
    uuid_fields = build.get("uuid_fields", {})
    batch_id = batch_id or new_batch_id()
    result = {"ok": False, "batch_id": batch_id, "layers": {},
              "totals": {"inserted": 0, "updated": 0, "deleted": 0},
              "errors": []}

    if QgsVectorLayer is None:
        result["errors"].append("QGIS not available")
        return result

    applied_layers = []
    for i, plan in enumerate(plans):
        if progress_cb:
            progress_cb(int(i / max(len(plans), 1) * 80), f"Applying {plan.layer}")
        if not plan.has_applicable_changes():
            result["layers"][plan.layer] = {"ok": True, "inserted": 0,
                                            "updated": 0, "deleted": 0,
                                            "errors": []}
            applied_layers.append(plan.layer)
            continue
        master_layer = _open(master_gpkg, plan.layer)
        if master_layer is None:
            result["errors"].append(f"master layer missing: {plan.layer}")
            continue
        res = commit_mod.apply_plan(
            master_layer, plan, mapper=mapper, batch_id=batch_id,
            uuid_field=uuid_fields.get(plan.layer, "UUID"))
        result["layers"][plan.layer] = res
        for k in ("inserted", "updated", "deleted"):
            result["totals"][k] += res.get(k, 0)
        if res.get("ok"):
            applied_layers.append(plan.layer)
        else:
            result["errors"].extend(res.get("errors", []))

    all_ok = not result["errors"]

    # Advance the base ONLY on a fully clean apply, so a partial failure can be
    # retried against the unchanged base.
    if all_ok:
        if progress_cb:
            progress_cb(90, "Advancing base snapshot")
        log = ReconcileChangelog(master_gpkg)
        snapshots = {}
        for name, payloads in captures.items():
            snapshots[name] = snapshot_from_payloads(
                name, uuid_fields.get(name, "UUID"), payloads)
        master_version = log.current_version() + 1
        checkout.update_base(master_gpkg, template_id, snapshots,
                             master_version=master_version, mapper=mapper)
        try:
            checkout.CheckoutRegistry(master_gpkg).mark_reconciled(
                template_id, master_version=master_version)
        except Exception:
            pass
        log.log_reconcile(batch_id, template_id, mapper, plans,
                          applied=result["totals"])
        result["ok"] = True

    if progress_cb:
        progress_cb(100, "Reconcile complete")
    return result


def register_and_snapshot(master_gpkg: str, template_path: str,
                          mapper: str = "",
                          layer_names: Optional[List[str]] = None) -> dict:
    """Record a template handout and store its base snapshot.

    For a blank template the base is empty (all future features classify as
    inserts on first sync). Called from the template-loader hook.
    """
    layer_names = layer_names or LGS_LAYERS
    template_id = checkout.template_id_from_path(template_path)
    out = {"template_id": template_id, "snapshotted": {}, "errors": []}

    if QgsVectorLayer is None:
        out["errors"].append("QGIS not available")
        return out

    snapshots = {}
    for name in layer_names:
        tpl_layer = _open(template_path, name)
        if tpl_layer is None:
            continue
        uuid_field = _uuid_field(tpl_layer)
        master_layer = _open(master_gpkg, name)
        transform = _transform(tpl_layer, master_layer) if master_layer else None
        payloads, _ = capture_layer(tpl_layer, uuid_field=uuid_field,
                                    transform=transform)
        snapshots[name] = snapshot_from_payloads(name, uuid_field, payloads)
        out["snapshotted"][name] = len(payloads)

    try:
        master_version = ReconcileChangelog(master_gpkg).current_version()
        checkout.save_base(master_gpkg, template_id, snapshots,
                           master_version=master_version, mapper=mapper)
        checkout.CheckoutRegistry(master_gpkg).register(
            template_id, template_path, mapper, master_version=master_version)
    except Exception as exc:
        out["errors"].append(str(exc))
    return out
