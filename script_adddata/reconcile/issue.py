#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Issue Field Copy: create a properly-stamped working copy from the master.

This is the deliberate hand-out (and RE-ISSUE) operation the reconcile
workflow was missing: the office cleans the master, issues each mapper a
copy, and every copy leaves the building already carrying its embedded
checkout identity + base snapshot (basestore/engine.stamp_checkout) - so
the base can never be recorded late and deletes/split/merge lineage always
have their ancestor.

Three source modes, chosen per hand-out:
- full   the whole master (everyone sees all mapping),
- blank  schema, styles and lookup tables only, no features,
- clip   only features intersecting an AOI (per-mapper areas).

QGIS-bound (layer edits + stamping) but import-safe headlessly like
engine.py. Pure decisions (destination naming) stay module-level testable.
"""

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

try:  # package context
    from . import basestore
    from . import engine
    from . import migrate
    from .checkout import master_stem
except ImportError:  # standalone
    import basestore
    import engine
    import migrate
    from checkout import master_stem

try:  # pragma: no cover - only inside QGIS
    from qgis.core import QgsVectorLayer, QgsGeometry, QgsFeatureRequest
except Exception:  # pragma: no cover
    QgsVectorLayer = None

MODE_FULL = basestore.MODE_FULL
MODE_BLANK = basestore.MODE_BLANK
MODE_CLIP = basestore.MODE_CLIP


def default_destination(master_gpkg: str, mapper: str = "",
                        when: Optional[datetime] = None) -> str:
    """<master_dir>/handouts/<master_stem>_<mapper>_<YYYYMMDD>.gpkg

    Purely a suggestion - checkout identity is the embedded checkout_id, so
    the filename no longer matters for reconcile; it only helps humans tell
    tablets apart.
    """
    when = when or datetime.now(timezone.utc)
    stamp = when.strftime("%Y%m%d")
    who = "".join(c for c in (mapper or "").strip() if c.isalnum()) or "copy"
    name = f"{master_stem(master_gpkg)}_{who}_{stamp}.gpkg"
    return os.path.join(os.path.dirname(master_gpkg), "handouts", name)


def _blank_layer(layer) -> Optional[str]:
    """Remove every feature from a layer (provider-direct). None = ok."""
    provider = layer.dataProvider()
    try:
        if provider.truncate():
            layer.updateExtents()
            return None
    except Exception:
        pass
    ids = [f.id() for f in layer.getFeatures()]
    if not ids:
        return None
    if provider.deleteFeatures(ids):
        layer.updateExtents()
        return None
    return f"could not clear features from {layer.name()}"


def _clip_layer(layer, aoi: "QgsGeometry") -> Optional[str]:
    """Delete every feature NOT intersecting the AOI (master CRS). None = ok.

    The copy shares the master's CRS, so the AOI needs no transform. Exact
    intersects (not just bbox) so a mapper's area boundary is honoured.
    """
    bbox = aoi.boundingBox()
    keep = set()
    for feat in layer.getFeatures(QgsFeatureRequest().setFilterRect(bbox)):
        g = feat.geometry()
        if g is not None and not g.isNull() and aoi.intersects(g):
            keep.add(feat.id())
    doomed = [f.id() for f in layer.getFeatures() if f.id() not in keep]
    if doomed and not layer.dataProvider().deleteFeatures(doomed):
        return f"could not clip features from {layer.name()}"
    layer.updateExtents()
    return None


def _vacuum(gpkg: str):
    """Shrink the copy after clipping/blanking. Best-effort."""
    try:
        con = sqlite3.connect(gpkg, timeout=5)
        try:
            con.execute("VACUUM")
        finally:
            con.close()
    except sqlite3.Error:
        pass


def issue_copy(master_gpkg: str, dest_path: str, mode: str = MODE_FULL,
               mapper: str = "", area_wkt: str = "",
               layer_names: Optional[List[str]] = None,
               progress_cb=None, transform_context=None) -> dict:
    """Create + stamp a working copy. Returns a report dict.

    Refuses an unmigrated master (this is the front door - the copy's base
    would be poison without UUIDs) and refuses to overwrite an existing
    destination. On any error before stamping, the partial copy is removed
    so a half-issued file can't circulate.
    """
    out = {"ok": False, "checkout_id": None, "dest_path": dest_path,
           "mode": mode, "feature_counts": {}, "skipped_no_uuid": {},
           "errors": []}

    def emit(pct, msg):
        if progress_cb:
            progress_cb(pct, msg)

    if QgsVectorLayer is None:
        out["errors"].append("QGIS not available")
        return out
    if not os.path.exists(master_gpkg):
        out["errors"].append("master GeoPackage not found")
        return out
    if os.path.exists(dest_path):
        out["errors"].append(
            f"destination already exists: {os.path.basename(dest_path)} - "
            "pick a new name (never overwrite a copy that may hold edits)")
        return out
    if mode not in (MODE_FULL, MODE_BLANK, MODE_CLIP):
        out["errors"].append(f"unknown mode: {mode}")
        return out
    if mode == MODE_CLIP and not (area_wkt or "").strip():
        out["errors"].append("clip mode needs an area (AOI)")
        return out

    emit(2, "Checking master migration")
    status = migrate.migration_status(master_gpkg)
    if not status.get("migrated"):
        out["errors"].append(
            "master has not been migrated for reconcile - run 'Verify / "
            "migrate master' first (one-off, safe to re-run)")
        return out

    aoi = None
    if mode == MODE_CLIP:
        aoi = QgsGeometry.fromWkt(area_wkt)
        if aoi is None or aoi.isNull() or aoi.isEmpty():
            out["errors"].append("could not parse the clip area WKT")
            return out

    layer_names = layer_names or list(migrate.LGS_LAYERS)

    emit(10, "Copying master")
    try:
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        shutil.copy2(master_gpkg, dest_path)
        for suffix in ("-wal", "-shm"):
            side = master_gpkg + suffix
            if os.path.exists(side):
                shutil.copy2(side, dest_path + suffix)
    except OSError as exc:
        out["errors"].append(f"copy failed: {exc}")
        return out

    try:
        if mode in (MODE_BLANK, MODE_CLIP):
            for i, name in enumerate(layer_names):
                emit(20 + int(i / max(len(layer_names), 1) * 40),
                     f"{'Blanking' if mode == MODE_BLANK else 'Clipping'} "
                     f"{name}")
                lyr = engine._open(dest_path, name)
                if lyr is None:
                    continue
                err = (_blank_layer(lyr) if mode == MODE_BLANK
                       else _clip_layer(lyr, aoi))
                if err:
                    out["errors"].append(err)
                del lyr  # release the OGR handle before VACUUM/stamping
            if out["errors"]:
                raise RuntimeError("; ".join(out["errors"]))
            emit(65, "Compacting the copy")
            _vacuum(dest_path)

        emit(75, "Stamping checkout identity + base")
        stamped = engine.stamp_checkout(
            master_gpkg, dest_path, mapper=mapper, source_mode=mode,
            area_wkt=area_wkt or "", layer_names=layer_names,
            transform_context=transform_context, register=True)
        out["checkout_id"] = stamped.get("checkout_id")
        out["feature_counts"] = stamped.get("snapshotted", {})
        out["skipped_no_uuid"] = stamped.get("skipped_no_uuid", {})
        out["errors"].extend(stamped.get("errors", []))
        if not out["checkout_id"]:
            raise RuntimeError("stamping failed")
    except Exception as exc:
        if str(exc) not in "; ".join(out["errors"]):
            out["errors"].append(str(exc))
        # A half-issued copy must not circulate: remove it.
        for path in (dest_path, dest_path + "-wal", dest_path + "-shm"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        out["dest_path"] = None
        return out

    emit(100, "Copy issued")
    out["ok"] = not out["errors"]
    return out
