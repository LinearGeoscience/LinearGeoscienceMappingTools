#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end test for the "prepare field data" step that hardcodes a working
template in place BEFORE reconcile. MUST run inside QGIS (needs the QGIS API).

It builds fixtures from a COPY of Template/LGS_MappingTemplate.gpkg (never the
real data), migrates the master, then:

  1. adds a field-collected point to the working template with a BLANK UUID,
     a raw Subtype1 legend code and a geometry but no MappedEasting/Northing;
  2. runs hardcode_data.runner.hardcode_geopackage() on the template;
  3. asserts the derived fields were baked in place — UUID filled, Legend filled
     from the lookup, MappedEasting filled from geometry, ProjectID set, lgs_*
     columns injected — and that re-running is a no-op (idempotent, empty-only);
  4. asserts reconcile then classifies the prepared feature as a CLEAN INSERT
     (a real UUID, no blanking conflict) — i.e. preparing first is what lets a
     field-collected feature merge cleanly.

How to run (QGIS Python console):
    exec(open(r"<repo>/tests/reconcile/test_hardcode_prepare_qgis.py").read())
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

import engine            # noqa: E402  (resolves via RECONCILE_DIR on sys.path)
import migrate           # noqa: E402

from hardcode_data.runner import hardcode_geopackage  # noqa: E402

from qgis.core import (QgsVectorLayer, QgsFeature, QgsGeometry,  # noqa: E402
                       QgsPointXY)

LAYER = "1 - FieldNotebook"
LOOKUP = "FieldNotebookCodes"
SUBTYPE_FIELD = "Subtype1"
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


def _is_blank(value):
    if value is None:
        return True
    if hasattr(value, "isNull"):
        try:
            if value.isNull():
                return True
        except Exception:
            pass
    text = str(value).strip()
    return text == "" or text == "NULL"


def _layer(gpkg, name):
    lyr = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
    assert lyr.isValid(), f"could not open {name} in {gpkg}"
    return lyr


def _field_names(gpkg, name):
    return {f.name() for f in _layer(gpkg, name).fields()}


def _fids(gpkg, name):
    return {f.id() for f in _layer(gpkg, name).getFeatures()}


def _feature_by_id(gpkg, name, fid):
    for f in _layer(gpkg, name).getFeatures():
        if f.id() == fid:
            return f
    return None


def _first_lookup_code(gpkg, table):
    """First (Code, Description) pair in a lookup table, or (None, None)."""
    lyr = QgsVectorLayer(f"{gpkg}|layername={table}", table, "ogr")
    if not lyr.isValid():
        return None, None
    names = {f.name() for f in lyr.fields()}
    if "Code" not in names or "Description" not in names:
        return None, None
    for f in lyr.getFeatures():
        code, desc = f["Code"], f["Description"]
        if not _is_blank(code) and not _is_blank(desc):
            return str(code).strip(), str(desc).strip()
    return None, None


def _add_raw_point(gpkg, subtype_code, x=500123.4, y=7000123.4):
    """Add a FieldNotebook point with BLANK UUID + raw code + geometry."""
    lyr = _layer(gpkg, LAYER)
    fields = lyr.fields()
    lyr.startEditing()
    feat = QgsFeature(fields)
    if subtype_code is not None and fields.indexOf(SUBTYPE_FIELD) != -1:
        feat.setAttribute(fields.indexOf(SUBTYPE_FIELD), subtype_code)
    # Deliberately leave UUID, MappedEasting/Northing, ProjectID empty.
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    lyr.addFeature(feat)
    assert lyr.commitChanges(), lyr.commitErrors()


def main():
    template = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
    if not os.path.exists(template):
        print(f"Template not found: {template}")
        return 1

    tmp = tempfile.mkdtemp(prefix="lgs_hardcode_")
    master = os.path.join(tmp, "LGS_Master_28350.gpkg")
    working = os.path.join(tmp, "LGS_SiteA_28350.gpkg")
    shutil.copy(template, master)
    shutil.copy(template, working)
    print(f"fixtures in {tmp}")

    print("\n[migrate master]")
    report = migrate.run_migration(master)
    check(report.get("ok"), "migration ok")

    print("\n[register handout -> empty base]")
    reg = engine.register_and_snapshot(master, working, mapper="HW")
    check(not reg.get("errors"), "register_and_snapshot ok")

    code, desc = _first_lookup_code(working, LOOKUP)
    has_subtype = SUBTYPE_FIELD in _field_names(working, LAYER)
    print(f"\n[add raw field point]  code={code!r} subtype_field={has_subtype}")
    before_fids = _fids(working, LAYER)
    _add_raw_point(working, code)
    new_fids = _fids(working, LAYER) - before_fids
    check(len(new_fids) == 1, "one feature added to the template")
    new_fid = next(iter(new_fids))
    raw = _feature_by_id(working, LAYER, new_fid)
    check(raw is not None and _is_blank(raw["UUID"]),
          "new feature has a BLANK UUID before prepare")

    print("\n[prepare / hardcode the template in place]")
    out = hardcode_geopackage(
        working, project_id="P-TEST", mapped_scale="1:1000",
        lookup_sources=[working, master])
    check(not out.get("errors"), f"hardcode ran without errors ({out.get('errors')})")
    check(out["totals"]["uuids_filled"] >= 1, "at least one UUID backfilled")

    baked = _feature_by_id(working, LAYER, new_fid)
    names = _field_names(working, LAYER)
    check(baked is not None and not _is_blank(baked["UUID"]),
          "UUID filled by prepare")
    check("lgs_version" in names and "lgs_feature_hash" in names,
          "lgs_* provenance columns injected")
    check("MappedEasting" in names and not _is_blank(baked["MappedEasting"]),
          "MappedEasting filled (from geometry fallback)")
    check(str(baked["ProjectID"]) == "P-TEST", "ProjectID standard field filled")
    if code is not None and has_subtype:
        check(str(baked["Legend"]) == desc,
              f"Legend filled from lookup ({code} -> {desc})")
    else:
        print("  skip: no usable legend code/field for the Legend assertion")

    print("\n[idempotent re-run]")
    out2 = hardcode_geopackage(
        working, project_id="P-TEST", mapped_scale="1:1000",
        lookup_sources=[working, master])
    check(out2["totals"]["applied"] == 0, "re-running prepare is a no-op")

    print("\n[reconcile classifies it as a clean insert]")
    uid = str(baked["UUID"])
    build = engine.build_plans(master, working)
    plan = next(p for p in build["plans"] if p.layer == LAYER)
    check(any(o.uuid == uid for o in plan.clean_inserts),
          "prepared feature classifies as a clean insert")
    check(not any(c.uuid == uid for c in plan.conflicts),
          "prepared feature raises no blanking conflict")

    print(f"\n{_passed} checks passed, {_failed} failed   (fixtures: {tmp})")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
else:
    # When exec()'d in the QGIS console, run immediately.
    main()
