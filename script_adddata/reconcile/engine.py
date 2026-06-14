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
    from .snapshot import (capture_layer, snapshot_from_payloads,
                           LayerSnapshot, FeatureFingerprint)
    from .reconcile import classify, compute_next_base, ReconcilePlan, RES_SKIP
    from .changelog import ReconcileChangelog
    from .locking import ReconcileLock
    from . import lineage
    from . import tombstones as tombstones_mod
    from . import commit as commit_mod
    from .migrate import LGS_LAYERS
except ImportError:  # standalone
    import checkout
    from snapshot import (capture_layer, snapshot_from_payloads,
                          LayerSnapshot, FeatureFingerprint)
    from reconcile import classify, compute_next_base, ReconcilePlan, RES_SKIP
    from changelog import ReconcileChangelog
    from locking import ReconcileLock
    import lineage
    import tombstones as tombstones_mod
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
           "master_captures": {}, "reports": {}, "uuid_fields": {},
           "missing_layers": [], "errors": [], "master_version_at_build": None}

    if QgsVectorLayer is None:
        out["errors"].append("QGIS not available")
        return out

    # Snapshot the master version at build time so apply can detect that someone
    # else reconciled in between (optimistic concurrency check).
    try:
        out["master_version_at_build"] = ReconcileChangelog(
            master_gpkg).current_version()
    except Exception:
        pass

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
        # Capture master PAYLOADS (not just fingerprints) so the field-level
        # three-way merge and conflict resolution have master's actual values.
        master_payloads, _ = capture_layer(
            master_layer, uuid_field=master_uuid_field, transform=None)
        base_fp = checkout.load_base_layer(master_gpkg, template_id, name)

        plan = classify(name, uuid_field, base_fp,
                        working_payloads, master_payloads)

        # Split/merge proposals from the residual (children = working inserts;
        # parents = master geometry of the just-deleted features). Polygons only.
        try:
            child_payloads = {op.uuid: op.payload
                              for op in plan.clean_inserts if op.payload}
            parent_payloads = {op.uuid: master_payloads[op.uuid]
                               for op in plan.clean_deletes
                               if op.uuid in master_payloads}
            splits, merges = lineage.detect_lineage(
                name, child_payloads, parent_payloads)
            plan.splits = splits
            plan.merges = merges
        except Exception as exc:  # pragma: no cover - never block a preview
            out["errors"].append(f"lineage {name}: {exc}")

        out["plans"].append(plan)
        out["captures"][name] = working_payloads
        out["master_captures"][name] = master_payloads
        out["reports"][name] = wreport
        out["uuid_fields"][name] = uuid_field

    return out


def _fp_map(payloads) -> Dict[str, FeatureFingerprint]:
    return {u: p.fingerprint() for u, p in (payloads or {}).items()}


def apply_plans(master_gpkg: str, template_path: str, build: dict,
                mapper: str = "", batch_id: Optional[str] = None,
                resolutions: Optional[dict] = None,
                force_lock: bool = False, progress_cb=None) -> dict:
    """Commit each plan's applicable ops (clean + auto-merge + resolved
    conflicts), then advance the base per-feature and log it.

    Concurrency-safe: aborts if the master changed since the preview was built
    (optimistic version check) or another reconcile holds the advisory lock
    (override with force_lock). Base advance is per-layer: a layer whose commit
    errors keeps its old base for retry; unresolved conflicts keep their old
    base entry so they re-surface next sync.

    `resolutions` (optional) maps "<layer>\\x1f<uuid>" -> resolution string and
    is applied onto the plans' ConflictRecords before committing; if omitted the
    plans already carry whatever the UI set.
    """
    template_id = build["template_id"]
    plans: List[ReconcilePlan] = build["plans"]
    captures = build.get("captures", {})
    master_captures = build.get("master_captures", {})
    uuid_fields = build.get("uuid_fields", {})
    batch_id = batch_id or new_batch_id()
    result = {"ok": False, "aborted": False, "batch_id": batch_id, "layers": {},
              "totals": {"inserted": 0, "updated": 0, "deleted": 0},
              "unresolved_conflicts": 0, "errors": []}

    if QgsVectorLayer is None:
        result["errors"].append("QGIS not available")
        return result

    if resolutions:
        _apply_resolutions(plans, resolutions)

    log = ReconcileChangelog(master_gpkg)

    # --- optimistic concurrency: did the master move since we built? ---
    built_at = build.get("master_version_at_build")
    if built_at is not None and log.current_version() != built_at:
        result["aborted"] = True
        result["errors"].append(
            f"Master changed since the preview was built "
            f"(version {built_at} -> {log.current_version()}). "
            f"Rebuild the preview before applying.")
        return result

    lock = ReconcileLock(master_gpkg, mapper=mapper)
    acquired, holder = lock.acquire(force=force_lock)
    if not acquired:
        result["aborted"] = True
        result["lock_holder"] = holder
        who = (holder or {}).get("mapper") or "another user"
        since = (holder or {}).get("acquired_utc") or "?"
        result["errors"].append(
            f"A reconcile is already in progress ({who}, since {since}). "
            f"Wait and retry, or override the lock.")
        return result

    try:
        old_full = checkout.load_base(master_gpkg, template_id)
        old_layers = (old_full or {}).get("layers", {}) if old_full else {}
        new_base_layers: Dict[str, LayerSnapshot] = {}
        all_tombstones = []

        for i, plan in enumerate(plans):
            if progress_cb:
                progress_cb(int(i / max(len(plans), 1) * 80),
                            f"Applying {plan.layer}")
            result["unresolved_conflicts"] += sum(
                1 for c in plan.conflicts
                if c.effective_resolution() == RES_SKIP)
            uf = uuid_fields.get(plan.layer, "UUID")
            # Stamp accepted split/merge groups (lgs_parent_uuid / lgs_merged_from
            # + parent attr-carry) onto the insert ops before they are applied.
            try:
                lineage.stamp_accepted(
                    plan, master_captures.get(plan.layer, {}))
            except Exception as exc:  # pragma: no cover - defensive
                result["errors"].append(f"lineage stamp {plan.layer}: {exc}")
            inserts, updates, deletes = plan.applicable_ops()

            if not (inserts or updates or deletes):
                res = {"ok": True, "inserted": 0, "updated": 0,
                       "deleted": 0, "errors": []}
            else:
                master_layer = _open(master_gpkg, plan.layer)
                if master_layer is None:
                    result["errors"].append(
                        f"master layer missing: {plan.layer}")
                    continue
                res = commit_mod.apply_plan(
                    master_layer, plan, mapper=mapper, batch_id=batch_id,
                    uuid_field=uf)
            result["layers"][plan.layer] = res
            for k in ("inserted", "updated", "deleted"):
                result["totals"][k] += res.get(k, 0)

            if res.get("ok"):
                all_tombstones.extend(res.get("tombstones", []))
                nb = compute_next_base(
                    plan, old_layers.get(plan.layer),
                    _fp_map(captures.get(plan.layer)),
                    _fp_map(master_captures.get(plan.layer)))
                new_base_layers[plan.layer] = LayerSnapshot(
                    layer_name=plan.layer, uuid_field=uf, features=nb)
            else:
                result["errors"].extend(res.get("errors", []))
                # Keep the old base for this layer so a retry is clean.
                if plan.layer in old_layers:
                    new_base_layers[plan.layer] = LayerSnapshot(
                        layer_name=plan.layer, uuid_field=uf,
                        features=dict(old_layers[plan.layer]))

        # Preserve base layers that weren't part of this run (e.g. the template
        # lacked them) so update_base doesn't drop them.
        for name, fps in old_layers.items():
            if name not in new_base_layers:
                new_base_layers[name] = LayerSnapshot(
                    layer_name=name, uuid_field=uuid_fields.get(name, "UUID"),
                    features=dict(fps))

        # Persist tombstones for the features actually removed (audit/recover).
        if all_tombstones:
            try:
                tombstones_mod.append_tombstones(master_gpkg, all_tombstones)
            except Exception as exc:  # pragma: no cover - non-fatal
                result["errors"].append(f"tombstones: {exc}")
        result["tombstones_written"] = len(all_tombstones)

        if progress_cb:
            progress_cb(90, "Advancing base snapshot")
        master_version = log.current_version() + 1
        try:
            checkout.update_base(master_gpkg, template_id, new_base_layers,
                                 master_version=master_version, mapper=mapper)
        except Exception as exc:  # I/O failure: surface, don't crash the caller
            result["errors"].append(f"base update failed: {exc}")
        try:
            checkout.CheckoutRegistry(master_gpkg).mark_reconciled(
                template_id, master_version=master_version)
        except Exception:
            pass
        notes = (f"partial: {len(result['errors'])} layer error(s)"
                 if result["errors"] else "")
        try:
            log.log_reconcile(batch_id, template_id, mapper, plans,
                              applied=result["totals"], notes=notes)
        except Exception as exc:  # base already advanced; changelog is non-fatal
            result["errors"].append(f"changelog write failed: {exc}")
        result["ok"] = not result["errors"]
    finally:
        lock.release()

    if progress_cb:
        progress_cb(100, "Reconcile complete")
    return result


def _apply_resolutions(plans, resolutions: dict):
    """Stamp UI-chosen resolutions onto the plans' conflicts.

    Keyed by "<layer>\\x1f<uuid>"; values are reconcile.RES_* strings.
    """
    for plan in plans:
        for c in plan.conflicts:
            key = f"{plan.layer}\x1f{c.uuid}"
            if key in resolutions and resolutions[key]:
                c.resolution = resolutions[key]


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
