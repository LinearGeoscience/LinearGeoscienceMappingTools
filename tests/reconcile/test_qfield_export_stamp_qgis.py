#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QGIS-bound tests for the QField exporter's reconcile stamping hook.

Drives OfflineConverter directly (no GUI) on a scratch project and asserts:
- an exported copy of a migrated master's mapping layers gets lgs_checkout
  (source_mode 'export') + lgs_base, and the master's registry records it,
- the embedded tables stay invisible to OGR sublayer listing,
- a non-canonical (decoy) gpkg is left unstamped,
- an unmigrated master exports WITH a warning and WITHOUT a stamp,
- register_reconcile=False disables the whole hook.

Run headless:
    python-qgis-ltr.bat run_headless_qgis.py test_qfield_export_stamp_qgis.py
"""

import os
import sys
import shutil
import tempfile

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
RECONCILE_DIR = os.path.join(REPO_ROOT, "script_adddata", "reconcile")
for p in (REPO_ROOT, RECONCILE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import migrate           # noqa: E402
import checkout          # noqa: E402
import basestore         # noqa: E402

from qgis.core import (QgsProject, QgsVectorLayer, QgsFeature,  # noqa: E402
                       QgsGeometry, QgsPointXY)

from qfield_export.core.offline_converter import OfflineConverter  # noqa: E402

LAYER = "1 - FieldNotebook"
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


def _add_point(gpkg, uuid, x=1.0, y=2.0):
    lyr = QgsVectorLayer(f"{gpkg}|layername={LAYER}", LAYER, "ogr")
    assert lyr.isValid()
    lyr.startEditing()
    feat = QgsFeature(lyr.fields())
    feat.setAttribute(lyr.fields().indexOf("UUID"), uuid)
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    lyr.addFeature(feat)
    assert lyr.commitChanges(), lyr.commitErrors()


def _run_export(project, layers, export_dir, register=True):
    """Drive the converter synchronously; returns (ok, warnings, logs)."""
    conv = OfflineConverter(project, export_dir,
                            [lyr.id() for lyr in layers],
                            include_zfilter_plugin=False,
                            include_scale_plugin=False,
                            include_opacity_plugin=False,
                            include_clipping_plugin=False,
                            include_spline_plugin=False,
                            include_reshape_plugin=False,
                            include_reverse_plugin=False,
                            include_copyattrs_plugin=False,
                            include_merge_plugin=False,
                            include_layerswitch_plugin=False,
                            register_reconcile=register)
    warnings, logs = [], []
    conv.warning.connect(warnings.append)
    conv.log_message.connect(logs.append)
    results = []
    conv.finished.connect(results.append)
    conv.export()
    return (results and results[0], warnings, logs)


def _sublayer_tables(gpkg):
    lyr = QgsVectorLayer(gpkg, "probe", "ogr")
    out = set()
    for s in lyr.dataProvider().subLayers():
        parts = s.split("!!::!!")
        if len(parts) > 1:
            out.add(parts[1])
    return out


def main():
    template = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
    if not os.path.exists(template):
        print(f"Template not found: {template}")
        return 1

    tmp = tempfile.mkdtemp(prefix="lgs_exstamp_")
    print(f"fixtures in {tmp}")
    master = os.path.join(tmp, "LGS_Master_28350.gpkg")
    shutil.copy(template, master)
    migrate.run_migration(master)
    _add_point(master, "E1")
    _add_point(master, "E2", x=5.0)

    decoy = os.path.join(tmp, "LGS_Decoy.gpkg")
    shutil.copy(template, decoy)

    project = QgsProject()
    m_layer = QgsVectorLayer(f"{master}|layername={LAYER}", LAYER, "ogr")
    d_layer = QgsVectorLayer(f"{decoy}|layername={LAYER}",
                             "Reference stuff", "ogr")
    assert m_layer.isValid() and d_layer.isValid()
    project.addMapLayer(m_layer)
    project.addMapLayer(d_layer)
    # _save_project reads the project's own file back, so it must exist.
    assert project.write(os.path.join(tmp, "proj1.qgs"))

    # --- stamped export ---
    print("\n[export stamps the mapping copy]")
    exp1 = os.path.join(tmp, "export1")
    os.makedirs(exp1)
    ok, warnings, logs = _run_export(project, [m_layer, d_layer], exp1)
    check(bool(ok), f"export ok (warnings: {warnings})")
    exported = os.path.join(exp1, os.path.basename(master))
    check(os.path.exists(exported), "master copy landed in the export dir")
    ck = basestore.read_checkout(exported)
    check(ck is not None and ck["source_mode"] == "export",
          "exported copy stamped with source_mode 'export'")
    check(ck and ck["master_id"] == basestore.read_master_uid(master),
          "stamp paired to the source master")
    base = basestore.read_base(exported)
    check(base is not None and {"E1", "E2"} <= set(
        base["layers"].get(LAYER, {})), "embedded base holds the features")
    entry = checkout.CheckoutRegistry(master).get(ck["checkout_id"]) if ck else None
    check(entry is not None and entry["status"] == "out",
          "master registry records the export checkout")
    check(any("Registered" in l and "reconcile" in l for l in logs),
          "log line announces the registration")

    exported_decoy = os.path.join(exp1, os.path.basename(decoy))
    check(os.path.exists(exported_decoy)
          and not basestore.has_checkout(exported_decoy),
          "non-canonical decoy exported WITHOUT a stamp")

    # lgs_changelog is deliberately registered (visible); the checkout/base
    # tables must NOT appear.
    tables = _sublayer_tables(exported)
    hidden = {basestore.CHECKOUT_TABLE, basestore.BASE_TABLE,
              basestore.BASE_META_TABLE}
    check(tables and not (tables & hidden),
          f"checkout/base tables invisible to OGR sublayers "
          f"({len(tables)} listed)")

    # --- unmigrated master: warn, don't stamp ---
    print("\n[unmigrated master]")
    raw = os.path.join(tmp, "LGS_Raw_28350.gpkg")
    shutil.copy(template, raw)
    project2 = QgsProject()
    r_layer = QgsVectorLayer(f"{raw}|layername={LAYER}", LAYER, "ogr")
    project2.addMapLayer(r_layer)
    assert project2.write(os.path.join(tmp, "proj2.qgs"))
    exp2 = os.path.join(tmp, "export2")
    os.makedirs(exp2)
    ok, warnings, _ = _run_export(project2, [r_layer], exp2)
    check(bool(ok), "export still succeeds")
    check(any("not been migrated" in w.lower()
              or "has not been" in w for w in warnings),
          f"loud warning about the unmigrated master ({warnings})")
    check(not basestore.has_checkout(os.path.join(exp2, os.path.basename(raw))),
          "no stamp on the copy from an unmigrated master")

    # --- opt-out ---
    print("\n[register_reconcile=False]")
    exp3 = os.path.join(tmp, "export3")
    os.makedirs(exp3)
    ok, warnings, _ = _run_export(project, [m_layer], exp3, register=False)
    check(bool(ok), "opt-out export ok")
    check(not basestore.has_checkout(os.path.join(exp3, os.path.basename(master))),
          "opt-out leaves the copy unstamped")

    print(f"\n{_passed} checks passed, {_failed} failed   (fixtures: {tmp})")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
else:
    main()
