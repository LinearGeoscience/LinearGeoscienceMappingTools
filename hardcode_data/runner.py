#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Path-based hardcode runner.

Bakes a working template GeoPackage *in place* by reusing the Hardcode Data &
Update Legends logic (analyze_layer / apply_layer_report) on layers opened
directly from a file path — no project membership required. This is the
"prepare the field data" step that must run before Reconcile / Merge: it fills
missing UUIDs (reconcile's identity), legend lookups, coordinate copies, the
standard fields and the lgs_* provenance columns, so field-collected features
reconcile cleanly instead of as spurious blanking conflicts.

Pure orchestration: it mirrors reconcile/engine._open() and delegates every
per-feature decision to hardcode_data.analysis. QGIS is imported lazily/guarded
so the module imports headlessly.
"""

from typing import Dict, List, Optional

try:  # package context
    from .analysis import (analyze_layer, apply_layer_report, LAYER_CONFIGS,
                           MODE_EMPTY_ONLY, SOURCE_UUID)
except ImportError:  # standalone
    from analysis import (analyze_layer, apply_layer_report, LAYER_CONFIGS,
                          MODE_EMPTY_ONLY, SOURCE_UUID)

try:  # pragma: no cover - only inside QGIS
    from qgis.core import QgsVectorLayer
except Exception:  # pragma: no cover
    QgsVectorLayer = None


def _open(gpkg: str, layer_name: str):
    """Open one layer of a GeoPackage by name, or None if absent/invalid."""
    if not gpkg:
        return None
    lyr = QgsVectorLayer(f"{gpkg}|layername={layer_name}", layer_name, "ogr")
    return lyr if lyr.isValid() else None


def _open_lookup(gpkgs: List[str], table_name: str):
    """First valid 'Code'+'Description' lookup table across the given gpkgs."""
    for gpkg in gpkgs:
        lyr = _open(gpkg, table_name)
        if lyr is None:
            continue
        names = {f.name() for f in lyr.fields()}
        if "Code" in names and "Description" in names:
            return lyr
    return None


def hardcode_geopackage(template_gpkg: str, *, project_id: str = "",
                        mapped_scale: str = "",
                        lookup_sources: Optional[List[str]] = None,
                        mode: int = MODE_EMPTY_ONLY,
                        layer_names: Optional[List[str]] = None,
                        progress_cb=None) -> dict:
    """Hardcode every standard layer of `template_gpkg` in place.

    `lookup_sources` is an ordered list of GeoPackages to search for the legend
    lookup tables (defaults to the template itself); the first one carrying a
    valid 'Code'/'Description' table wins. `mode` defaults to empty-only, so the
    pass only fills blanks and is safe to re-run.

    `progress_cb(pct, msg)` matches the reconcile dialog's callback (NOT the
    per-feature callback analyze_layer expects), so it is only called at the
    per-layer level here.

    Returns {ok, template_gpkg, layers: {name: {...}}, totals, errors}.
    """
    out = {"ok": False, "template_gpkg": template_gpkg, "layers": {},
           "totals": {"applied": 0, "uuids_filled": 0, "missing_codes": 0,
                      "duplicate_uuids": 0},
           "errors": []}

    if QgsVectorLayer is None:
        out["errors"].append("QGIS not available")
        return out

    layer_names = layer_names or list(LAYER_CONFIGS.keys())
    lookup_sources = [g for g in (lookup_sources or [template_gpkg]) if g]

    for i, name in enumerate(layer_names):
        if progress_cb:
            progress_cb(int(i / max(len(layer_names), 1) * 100),
                        f"Preparing {name}")
        config = LAYER_CONFIGS.get(name)
        if config is None:
            continue

        layer = _open(template_gpkg, name)
        if layer is None:
            out["layers"][name] = {"present": False}
            continue

        lookup_layer = None
        legend_cfg = config.get("legend")
        if legend_cfg:
            lookup_layer = _open_lookup(lookup_sources,
                                        legend_cfg["lookup_table"])

        try:
            # Pass the LAYER's own CRS as project_crs so MappedCRS is correct
            # and no spurious CRS-mismatch note fires.
            report = analyze_layer(
                layer, config, project_id=project_id,
                mapped_scale=mapped_scale,
                project_crs=layer.crs().authid(), mode=mode,
                lookup_layer=lookup_layer)
            applied, errors = apply_layer_report(layer, report)
        except Exception as exc:  # pragma: no cover - defensive
            out["layers"][name] = {"present": True, "applied": 0,
                                   "errors": [str(exc)]}
            out["errors"].append(f"{name}: {exc}")
            continue

        counts = report.counts_by_source()
        dups = (report.uuid_report.duplicates
                if report.uuid_report else {}) or {}
        entry = {
            "present": True,
            "applied": applied,
            "by_source": counts,
            "uuids_filled": counts.get(SOURCE_UUID, 0),
            "missing_codes": list(report.missing_codes),
            "duplicate_uuids": sorted(dups.keys()),
            "legend_skipped": report.legend_skipped_reason,
            "fields_created": list(report.fields_to_create),
            "errors": list(errors),
        }
        out["layers"][name] = entry
        out["totals"]["applied"] += applied
        out["totals"]["uuids_filled"] += entry["uuids_filled"]
        out["totals"]["missing_codes"] += len(entry["missing_codes"])
        out["totals"]["duplicate_uuids"] += len(entry["duplicate_uuids"])
        if errors:
            out["errors"].extend(f"{name}: {e}" for e in errors)

    out["ok"] = not out["errors"]
    return out
