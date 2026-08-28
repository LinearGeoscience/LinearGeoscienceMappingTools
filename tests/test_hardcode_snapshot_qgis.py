#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Snapshot-parity test for the hardcode preview (MUST run inside QGIS).

Asserts analyze_layer over a LayerScanSnapshot + pre-built lookup dict
(the background-task path) produces a report identical to analyze_layer
over the live QgsVectorLayer + lookup layer (the historical synchronous
path), on a copy of the bundled template with a couple of raw features.

Run via the same stdin-exec wrapper as the other *_qgis tests.
"""

import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
# Import through the plugin package so hardcode_data's relative imports
# (..script_adddata etc.) resolve.
PARENT = os.path.dirname(REPO_ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
PKG = os.path.basename(REPO_ROOT)

import importlib  # noqa: E402

from qgis.core import (QgsFeature, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsVectorLayer)

_analysis = importlib.import_module(PKG + ".hardcode_data.analysis")
LAYER_CONFIGS = _analysis.LAYER_CONFIGS
MODE_EMPTY_ONLY = _analysis.MODE_EMPTY_ONLY
LayerScanSnapshot = _analysis.LayerScanSnapshot
analyze_layer = _analysis.analyze_layer
build_lookup_dict = _analysis.build_lookup_dict

LAYER = "1 - FieldNotebook"
LOOKUP = "FieldNotebookCodes"
_passed = 0
_failed = 0


def check(cond, label):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"  FAIL {label}")


def _report_key(report):
    """Comparable projection of a LayerReport."""
    return {
        "layer_id": report.layer_id,
        "layer_name": report.layer_name,
        "feature_count": report.feature_count,
        "scoped": report.scoped_feature_count,
        "fields_to_create": list(report.fields_to_create),
        # UUID fills generate a random uuid4 as the new value, so compare
        # those changes without the value.
        "changes": sorted(
            (c.feature_id, c.field_name,
             "<uuid>" if c.source == "UUID fill" else str(c.new_value),
             c.source) for c in report.changes),
        "missing_codes": list(report.missing_codes),
        "uuid_missing": report.uuid_report.missing_count if report.uuid_report else None,
        "uuid_dups": sorted(report.uuid_report.duplicates)
        if report.uuid_report else None,
        "columns": [(s.name, s.filled, s.missing, s.distinct_count,
                     s.will_modify, s.is_new) for s in report.column_stats],
        "legend_skipped": report.legend_skipped_reason,
        "notes": list(report.notes),
    }


def main():
    template = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
    if not os.path.exists(template):
        print(f"Template not found: {template}")
        return 1

    tmp = tempfile.mkdtemp(prefix="lgs_snapshot_")
    gpkg = os.path.join(tmp, "working.gpkg")
    shutil.copy(template, gpkg)

    layer = QgsVectorLayer(f"{gpkg}|layername={LAYER}", LAYER, "ogr")
    check(layer.isValid(), "layer opens")

    # Two raw features: one with a legend code, one without.
    layer.startEditing()
    fields = layer.fields()
    f1 = QgsFeature(fields)
    code_idx = fields.indexOf(LAYER_CONFIGS[LAYER]["legend"]["source_field"])
    if code_idx != -1:
        f1.setAttribute(code_idx, "DigitisationComment")
    f1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(100.0, 200.0)))
    layer.addFeature(f1)
    f2 = QgsFeature(fields)
    f2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(150.0, 250.0)))
    layer.addFeature(f2)
    check(layer.commitChanges(), "fixture features committed")

    lookup = QgsVectorLayer(f"{gpkg}|layername={LOOKUP}", LOOKUP, "ogr")
    check(lookup.isValid(), "lookup opens")

    kwargs = dict(project_id="P123", mapped_scale="1:2500",
                  project_crs=layer.crs().authid(), mode=MODE_EMPTY_ONLY)
    config = LAYER_CONFIGS[LAYER]

    live = analyze_layer(layer, config, lookup_layer=lookup, **kwargs)
    snap = analyze_layer(LayerScanSnapshot(layer), config,
                         lookup_dict=build_lookup_dict(lookup), **kwargs)

    check(len(live.changes) > 0, f"live path found changes ({len(live.changes)})")
    lk, sk = _report_key(live), _report_key(snap)
    for key in lk:
        check(lk[key] == sk[key], f"snapshot report matches live: {key}")

    print(f"\n{_passed} checks passed, {_failed} failed   (fixtures: {tmp})")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
