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

import os
import uuid as uuid_module
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:  # package context
    from . import checkout
    from . import basestore
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
    import basestore
    from snapshot import (capture_layer, snapshot_from_payloads,
                          LayerSnapshot, FeatureFingerprint)
    from reconcile import classify, compute_next_base, ReconcilePlan, RES_SKIP
    from changelog import ReconcileChangelog
    from locking import ReconcileLock
    import lineage
    import tombstones as tombstones_mod
    import commit as commit_mod
    from migrate import LGS_LAYERS

try:
    from ...lgs_layers import gpkg_layer_name
except Exception:  # pragma: no cover
    from lgs_layers import gpkg_layer_name

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
    if lyr.isValid():
        return lyr
    # A GeoPackage checked out before the Aug-2026 Linework/Overlay swap numbers
    # those two layers the other way round. Without this the reconcile loop
    # would treat every layer as absent and sync nothing, silently.
    actual = gpkg_layer_name(gpkg, layer_name)
    if not actual or actual == layer_name:
        return None
    lyr = QgsVectorLayer(f"{gpkg}|layername={actual}", actual, "ogr")
    return lyr if lyr.isValid() else None


def _uuid_field(layer, default: str = "UUID") -> str:
    names = [f.name() for f in layer.fields()]
    if detect_uuid_field:
        return detect_uuid_field(names) or default
    return default if default in names else (names[0] if names else default)


def _transform(src_layer, dst_layer, context=None):
    """CRS transform between two layers.

    `context` may be a QgsCoordinateTransformContext captured on the main
    thread; without it we fall back to QgsProject.instance(), which is only
    safe when running on the main thread (background tasks must pass one).
    """
    try:
        scrs, dcrs = src_layer.crs(), dst_layer.crs()
        if scrs.isValid() and dcrs.isValid() and scrs != dcrs:
            return QgsCoordinateTransform(
                scrs, dcrs, context if context is not None
                else QgsProject.instance())
    except Exception:
        pass
    return None


def _master_fingerprints(master_layer, uuid_field) -> Dict[str, FeatureFingerprint]:
    payloads, _ = capture_layer(master_layer, uuid_field=uuid_field, transform=None)
    return {u: p.fingerprint() for u, p in payloads.items()}


def _resolve_base(master_gpkg: str, template_path: str,
                  template_id: str) -> dict:
    """Find the common ancestor for a working copy.

    Embedded (inside the working file) is the primary store; the legacy
    filename-keyed sidecar is the fallback and the apply-time recovery
    mirror. When both exist the newer capture wins (basestore.newest_base) -
    that heals the case where one of the two post-apply writes failed.

    Returns {"layers": {name: {uuid: fp}} | None, "source":
    "embedded"|"sidecar"|None, "checkout": dict|None, "captured_utc": ...}.
    layers None means no base anywhere -> classify() will synthesize.
    """
    embedded = basestore.read_base(template_path)
    sidecar = checkout.load_base(master_gpkg, template_id)
    base, source = basestore.newest_base(embedded, sidecar)
    return {
        "layers": base["layers"] if base else None,
        "source": source,
        "checkout": basestore.read_checkout(template_path),
        "captured_utc": (base or {}).get("captured_utc"),
    }


def build_plans(master_gpkg: str, template_path: str,
                layer_names: Optional[List[str]] = None,
                progress_cb=None, transform_context=None) -> dict:
    """Capture + classify every standard layer. Does NOT modify anything.

    Returns {plans: [ReconcilePlan], captures: {layer: working_payloads},
    reports: {layer: capture_report}, template_id, missing_layers, errors}.
    """
    layer_names = layer_names or LGS_LAYERS
    template_id = checkout.template_id_from_path(template_path)
    out = {"template_id": template_id, "plans": [], "captures": {},
           "master_captures": {}, "reports": {}, "uuid_fields": {},
           "missing_layers": [], "errors": [], "master_version_at_build": None,
           "checkout": None, "checkout_id": template_id, "base_source": None,
           "base_captured_utc": None, "master_mismatch": False,
           "guards": {"missing_from_master": {}}}

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

    # Resolve the common ancestor once: embedded (in the working file) first,
    # legacy sidecar second, newest capture wins.
    resolved = _resolve_base(master_gpkg, template_path, template_id)
    base_layers = resolved["layers"]
    ck = resolved["checkout"]
    out["checkout"] = ck
    out["base_source"] = resolved["source"]
    out["base_captured_utc"] = resolved["captured_utc"]
    if ck and ck.get("checkout_id"):
        out["checkout_id"] = ck["checkout_id"]

    # Pairing guard: a stamped working copy knows which master it was issued
    # from. Applying it to a DIFFERENT master would merge two unrelated maps,
    # so a uid mismatch is blocking. When either uid is unavailable (legacy
    # master, locked file) fall back to a warn-only basename comparison.
    if ck and ck.get("master_id"):
        master_uid = basestore.read_master_uid(master_gpkg)
        if master_uid and master_uid != ck["master_id"]:
            out["master_mismatch"] = True
            out["errors"].append(
                f"This working copy was issued from a different master "
                f"({ck.get('master_name') or 'unknown'}), not "
                f"{os.path.basename(master_gpkg)}. Applying would merge "
                f"unrelated maps - pick the right master.")
        elif not master_uid and ck.get("master_name") and \
                ck["master_name"] != os.path.basename(master_gpkg):
            out["errors"].append(
                f"warning: working copy was issued from "
                f"'{ck['master_name']}' but is being reconciled against "
                f"'{os.path.basename(master_gpkg)}' (master has no uid to "
                f"verify - continue only if the master was renamed).")

    # UUIDs already deleted through reconcile (tombstoned) are known-intended
    # deletes; subtract them from the missing-from-master guard below.
    try:
        tombstoned_uuids = {r.get("uuid")
                            for r in tombstones_mod.load_tombstones(master_gpkg)}
    except Exception:
        tombstoned_uuids = set()

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
        transform = _transform(tpl_layer, master_layer, transform_context)

        working_payloads, wreport = capture_layer(
            tpl_layer, uuid_field=uuid_field, transform=transform)
        # Capture master PAYLOADS (not just fingerprints) so the field-level
        # three-way merge and conflict resolution have master's actual values.
        master_payloads, _ = capture_layer(
            master_layer, uuid_field=master_uuid_field, transform=None)
        base_fp = (None if base_layers is None
                   else base_layers.get(name, {}))

        plan = classify(name, uuid_field, base_fp,
                        working_payloads, master_payloads)

        # Guard: base UUIDs the master doesn't hold, unchanged in the working
        # copy - classify() skips them as "master-only delete". For a properly
        # issued copy that IS the intent (office cleanup wins); for a base
        # registered AFTER field edits it silently strands the mapper's work
        # forever. The dialog words the warning by base_source; tombstoned
        # UUIDs (deletes applied through reconcile) are known-intended noise.
        if base_fp:
            missing = [
                u for u, reason in plan.skipped
                if reason.startswith("master-only delete")
                and u in working_payloads
                and u not in tombstoned_uuids
            ]
            if missing:
                out["guards"]["missing_from_master"][name] = {
                    "count": len(missing), "uuids": missing[:50]}

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
                try:
                    progress_cb(int(i / max(len(plans), 1) * 80),
                                f"Applying {plan.layer}")
                except Exception:
                    # Cancel requested (the caller's callback raises to stop
                    # us). Stop cleanly BETWEEN layers: layers already
                    # committed keep their changes, and the base/changelog
                    # advance below still runs for them so a re-sync stays
                    # consistent.
                    result["cancelled"] = True
                    result["errors"].append(
                        f"cancelled by user before layer: {plan.layer}")
                    break
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
            try:
                progress_cb(90, "Advancing base snapshot")
            except Exception:
                pass  # too late to stop: the base advance must complete
        master_version = log.current_version() + 1
        # The advanced base is written to BOTH stores. The embedded copy (in
        # the working file) is the primary - it travels with the file and is
        # what the next sync reads; the sidecar is the recovery mirror for
        # the case where the working file is locked right now (newest capture
        # wins at the next build, so double-writing is safe).
        captured_utc = _utc_now()
        try:
            checkout.update_base(master_gpkg, template_id, new_base_layers,
                                 master_version=master_version, mapper=mapper)
        except Exception as exc:  # I/O failure: surface, don't crash the caller
            result["errors"].append(f"base update failed: {exc}")
        ck = build.get("checkout")
        if ck:
            try:
                basestore.write_base(template_path, new_base_layers,
                                     master_version=master_version,
                                     captured_utc=captured_utc)
                result["embedded_base_refreshed"] = True
            except Exception as exc:
                result["embedded_base_refreshed"] = False
                result["errors"].append(
                    f"working-copy base refresh failed ({exc}); the sidecar "
                    f"carries the advanced base, the next sync will use it")
        try:
            checkout.CheckoutRegistry(master_gpkg).mark_reconciled(
                build.get("checkout_id") or template_id,
                master_version=master_version, mapper=mapper)
        except Exception:
            pass
        notes = (f"partial: {len(result['errors'])} layer error(s)"
                 if result["errors"] else "")
        try:
            log.log_reconcile(batch_id, template_id, mapper, plans,
                              applied=result["totals"], notes=notes,
                              checkout_id=(ck or {}).get("checkout_id", ""))
        except Exception as exc:  # base already advanced; changelog is non-fatal
            result["errors"].append(f"changelog write failed: {exc}")
        result["ok"] = not result["errors"]
    finally:
        lock.release()

    if progress_cb:
        try:
            progress_cb(100, "Reconcile complete")
        except Exception:
            pass
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


def _capture_snapshots(master_gpkg: str, working_gpkg: str,
                       layer_names: List[str],
                       transform_context=None) -> tuple:
    """Capture the working copy's canonical layers as LayerSnapshots.

    Geometry is hashed in the MASTER CRS (issued copies share it, so the
    transform is normally a no-op; the template loader may reproject).
    Returns (snapshots, counts, skipped_no_uuid).
    """
    snapshots: Dict[str, LayerSnapshot] = {}
    counts: Dict[str, int] = {}
    skipped: Dict[str, int] = {}
    for name in layer_names:
        wc_layer = _open(working_gpkg, name)
        if wc_layer is None:
            continue
        uuid_field = _uuid_field(wc_layer)
        master_layer = _open(master_gpkg, name)
        transform = (_transform(wc_layer, master_layer, transform_context)
                     if master_layer else None)
        payloads, report = capture_layer(wc_layer, uuid_field=uuid_field,
                                         transform=transform)
        snapshots[name] = snapshot_from_payloads(name, uuid_field, payloads)
        counts[name] = len(payloads)
        if report.get("skipped_no_uuid"):
            skipped[name] = report["skipped_no_uuid"]
    return snapshots, counts, skipped


def stamp_checkout(master_gpkg: str, working_gpkg: str, mapper: str = "",
                   source_mode: str = basestore.MODE_FULL, area_wkt: str = "",
                   layer_names: Optional[List[str]] = None,
                   transform_context=None, register: bool = True,
                   snapshots: Optional[Dict[str, LayerSnapshot]] = None
                   ) -> dict:
    """Stamp a working copy with its embedded checkout identity + base.

    THE moment the whole reconcile system depends on: runs when (and only
    when) a copy is created - the issue tool, the QField exporter, the
    template loader - so the base can never be recorded late. Drops any
    stale lgs_ tables first (a copy-of-a-copy must not inherit an identity),
    writes lgs_checkout + lgs_base, and registers the checkout with the
    master keyed by the fresh checkout_id.

    `snapshots` lets a caller that already captured the layers skip the
    re-capture. Returns {checkout_id, snapshotted:{layer:n},
    skipped_no_uuid:{layer:n}, errors:[]}; a failed stamp reports in errors
    and leaves the file unstamped (legacy behaviour) rather than half-done.
    """
    layer_names = layer_names or LGS_LAYERS
    out = {"checkout_id": None, "snapshotted": {}, "skipped_no_uuid": {},
           "errors": []}
    if QgsVectorLayer is None:
        out["errors"].append("QGIS not available")
        return out

    try:
        if snapshots is None:
            snapshots, counts, skipped = _capture_snapshots(
                master_gpkg, working_gpkg, layer_names, transform_context)
        else:
            counts = {n: len(s.features) for n, s in snapshots.items()}
            skipped = {n: s.skipped_no_uuid for n, s in snapshots.items()
                       if s.skipped_no_uuid}
        out["snapshotted"] = counts
        out["skipped_no_uuid"] = skipped

        master_version = ReconcileChangelog(master_gpkg).current_version()
        basestore.drop_embedded_tables(working_gpkg)
        row = basestore.write_checkout(working_gpkg, {
            "master_id": basestore.ensure_master_uid(master_gpkg),
            "master_name": os.path.basename(master_gpkg),
            "mapper": mapper,
            "master_version": master_version,
            "source_mode": source_mode,
            "area_wkt": area_wkt,
        })
        out["checkout_id"] = row["checkout_id"]
        basestore.write_base(working_gpkg, snapshots,
                             master_version=master_version)

        if register:
            checkout.CheckoutRegistry(master_gpkg).register_checkout({
                "checkout_id": row["checkout_id"],
                "template_id": checkout.template_id_from_path(working_gpkg),
                "template_path": working_gpkg,
                "mapper": mapper,
                "source_mode": source_mode,
                "area_wkt": area_wkt,
                "master_version": master_version,
                "issued_utc": row["issued_utc"],
            })
    except Exception as exc:
        out["errors"].append(str(exc))
    return out


def register_and_snapshot(master_gpkg: str, template_path: str,
                          mapper: str = "",
                          layer_names: Optional[List[str]] = None,
                          transform_context=None) -> dict:
    """Record a template handout: embedded stamp + legacy sidecar base.

    For a blank template the base is empty (all future features classify as
    inserts on first sync). Called from the template-loader hook. The
    embedded stamp is the primary identity; the sidecar base is still
    written for one release so an older plugin can read the same template.
    """
    layer_names = layer_names or LGS_LAYERS
    template_id = checkout.template_id_from_path(template_path)
    out = {"template_id": template_id, "snapshotted": {}, "errors": []}

    if QgsVectorLayer is None:
        out["errors"].append("QGIS not available")
        return out

    snapshots, out["snapshotted"], _skipped = _capture_snapshots(
        master_gpkg, template_path, layer_names, transform_context)

    # Sidecar FIRST, embedded stamp second: base resolution is newest-wins,
    # and the embedded store must never lose to its own back-compat mirror.
    try:
        master_version = ReconcileChangelog(master_gpkg).current_version()
        checkout.save_base(master_gpkg, template_id, snapshots,
                           master_version=master_version, mapper=mapper)
    except Exception as exc:
        out["errors"].append(str(exc))

    stamped = stamp_checkout(
        master_gpkg, template_path, mapper=mapper,
        source_mode=basestore.MODE_TEMPLATE, layer_names=layer_names,
        transform_context=transform_context, register=True,
        snapshots=snapshots)
    out["checkout_id"] = stamped.get("checkout_id")
    out["errors"].extend(stamped.get("errors", []))

    if not stamped.get("checkout_id"):
        # Embedded stamp failed -> keep the legacy registration so the
        # handout is at least tracked the old way.
        try:
            checkout.CheckoutRegistry(master_gpkg).register(
                template_id, template_path, mapper,
                master_version=master_version)
        except Exception as exc:
            out["errors"].append(str(exc))
    return out
