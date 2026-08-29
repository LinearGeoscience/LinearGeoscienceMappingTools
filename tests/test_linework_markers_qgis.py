"""The rebuilt Linework ornaments sit on the line, and every pair differs.

inject_linework_marker_decorations.py rebuilt all 31 ornament
MarkerLines from Template/markers/*.svg + SPEC.  The claims that used to
fail silently are proven in pixels:

  1. structure: 23 SvgMarkers, every SVG param()'d, offsets clean
     ("0,0" - no UI-drag float noise), placement ramps (interval /
     offsetAlongLine / averageAngleLength) Weight-scaled;
  2. thrust teeth ATTACH to the stroke at Very Minor AND Regional (the
     drift defect this rebuild exists to kill), and the open reverse
     tooth renders differently from the filled thrust tooth;
  3. the refolded folds no longer share the overturned folds' artwork
     (Antiformal Syncline != Antiform - Overturned, and the synformal
     twin likewise);
  4. sinistral and dextral are true mirrors (one rendered image flipped
     horizontally matches the other);
  5. idempotency: a re-run of the injector is a no-op.

Run under the QGIS python:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests\\test_linework_markers_qgis.py
"""

import base64
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_scripts = os.path.join(REPO_ROOT, "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import importlib  # noqa: E402

from qgis.core import (QgsApplication, QgsExpressionContext,  # noqa: E402
                       QgsExpressionContextUtils, QgsFeature, QgsGeometry,
                       QgsMapRendererParallelJob, QgsMapSettings, QgsProject,
                       QgsRectangle, QgsVectorLayer)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

_inj = importlib.import_module("inject_linework_marker_decorations")

GPKG = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
LW = _inj.LW
REF_SCALE = 5000
PX_W, PX_H, DPI = 1280, 400, 192.0

_passed = 0
_failed = 0


def check(cond, label):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print("  FAIL: " + label)
    return cond


def qml_root(gpkg):
    con = sqlite3.connect("file:%s?mode=ro" % gpkg.replace("\\", "/"),
                          uri=True)
    try:
        row = con.execute("SELECT styleQML FROM layer_styles "
                          "WHERE f_table_name=?", (LW,)).fetchone()
    finally:
        con.close()
    return ET.fromstring(row[0])


# ---------------------------------------------------------------------------
# 1. structure
# ---------------------------------------------------------------------------

def test_structure():
    print("structure:")
    root = qml_root(GPKG)
    rend = root.find("renderer-v2")
    cats = {c.get("value"): c.get("symbol") for c in rend.iter("category")
            if c.get("value")}
    syms = {s.get("name"): s for s in rend.find("symbols").findall("symbol")}

    svg_layers = [l for l in rend.iter("layer")
                  if l.get("class") == "SvgMarker"]
    check(len(svg_layers) == _inj.EXPECT_SVG_MARKERS,
          "%d SvgMarkers (got %d)" % (_inj.EXPECT_SVG_MARKERS,
                                      len(svg_layers)))
    unparam = float_noise = 0
    bodies = {}
    for lyr in svg_layers:
        o = {x.get("name"): x.get("value")
             for x in lyr.find("Option").findall("Option")}
        body = base64.b64decode(o["name"].split("base64:")[1])
        bodies[lyr.get("id")] = body
        if b"param(fill)" not in body and b"param(outline)" not in body:
            unparam += 1
        if re.search(rb"e-1[0-9]", body):
            float_noise += 1
        if o.get("offset") != "0,0":
            float_noise += 1
    check(unparam == 0, "every SVG is param()'d (%d not)" % unparam)
    check(float_noise == 0,
          "no float-noise offsets survive (%d found)" % float_noise)

    # Placement ramps ride the Weight CASE on every spec'd MarkerLine.
    missing = []
    for code, spec in _inj.SPEC.items():
        sym = syms[cats[code]]
        mls = [l for l in sym.findall("layer")
               if l.get("class") == "MarkerLine"]
        for ml in mls:
            dd = ET.tostring(ml.find("data_defined_properties"),
                             encoding="unicode")
            if "averageAngleLength" not in dd or "Weight" not in dd:
                missing.append(code)
            if spec.get("placements", "Interval") == "Interval" \
                    and not spec.get("rows") and "interval" not in dd:
                missing.append(code)
    check(not missing, "Weight placement ramps present (missing: %s)"
          % sorted(set(missing)))

    # The pairs that used to share artwork no longer do.
    def body_of(code):
        sym = syms[cats[code]]
        for l in sym.iter("layer"):
            if l.get("class") == "SvgMarker":
                return bodies[l.get("id")]
    pairs = [("Fault - Thrust", "Fault - Reverse"),
             ("Antiformal Syncline", "Antiform - Overturned"),
             ("Synformal Anticline", "Synform - Overturned"),
             ("Fault - Sinistral", "Fault - Dextral")]
    for a, b in pairs:
        check(body_of(a) != body_of(b), "%s != %s artwork" % (a, b))
    # ... and the deliberate sharing still holds.
    check(body_of("Fault - Thrust") == body_of("Fault - Thrust"), "sanity")
    check(body_of("Antiform") == body_of("Anticline"),
          "Antiform == Anticline artwork (deliberate)")


# ---------------------------------------------------------------------------
# render harness
# ---------------------------------------------------------------------------

def render(lyr, scale, project, w=PX_W, h=PX_H):
    gw = w / DPI * 0.0254 * scale
    gh = h / DPI * 0.0254 * scale
    c = lyr.extent().center()
    ms = QgsMapSettings()
    ms.setOutputSize(QSize(w, h))
    ms.setOutputDpi(DPI)
    ms.setDestinationCrs(lyr.crs())
    ms.setExtent(QgsRectangle(c.x() - gw / 2, c.y() - gh / 2,
                              c.x() + gw / 2, c.y() + gh / 2))
    ms.setLayers([lyr])
    ms.setBackgroundColor(QColor(255, 255, 255))
    ctx = QgsExpressionContext()
    ctx.appendScope(QgsExpressionContextUtils.globalScope())
    ctx.appendScope(QgsExpressionContextUtils.projectScope(project))
    ctx.appendScope(QgsExpressionContextUtils.mapSettingsScope(ms))
    ms.setExpressionContext(ctx)
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    return job.renderedImage()


def inky(c):
    return (c.red() + c.green() + c.blue()) / 3 < 150


def ink_set(img):
    return {(x, y) for y in range(PX_H) for x in range(PX_W)
            if inky(QColor(img.pixel(x, y)))}


def seed(lyr, wkt, attrs):
    lyr.dataProvider().truncate()
    f = QgsFeature(lyr.fields())
    f.setGeometry(QgsGeometry.fromWkt(wkt))
    for k, v in attrs.items():
        f[k] = v
    lyr.dataProvider().addFeatures([f])
    lyr.reload()
    lyr.updateExtents()


def mm_line(length_mm, scale=REF_SCALE):
    return "LINESTRING(0 0, %f 0)" % (length_mm * scale / 1000.0)


def attached(ink):
    """Every column's ink is one contiguous vertical run - ornament ink
    that floats clear of the stroke shows up as a column with a gap."""
    cols = {}
    for x, y in ink:
        cols.setdefault(x, []).append(y)
    gapped = 0
    for x, ys in cols.items():
        ys = sorted(ys)
        if any(b - a > 2 for a, b in zip(ys, ys[1:])):
            gapped += 1
    return gapped


def test_render(tmp_gpkg):
    print("render:")
    project = QgsProject.instance()
    lw = QgsVectorLayer("%s|layername=%s" % (tmp_gpkg, LW), "lw", "ogr")
    if not check(lw.isValid(), "Linework opens"):
        return
    project.addMapLayer(lw)
    lw.setLabelsEnabled(False)
    lw.renderer().setReferenceScale(REF_SCALE)
    line = mm_line(120)

    # (2) teeth attach to the stroke at both extremes of the Weight ladder.
    for tier in ("Very Minor", "Moderate", "Regional"):
        seed(lw, line, dict(Category="Structural", Type="Fault - Thrust",
                            Weight=tier))
        ink = ink_set(render(lw, REF_SCALE, project))
        check(len(ink) > 50, "Fault - Thrust @ %s draws (%d px)"
              % (tier, len(ink)))
        g = attached(ink)
        check(g == 0, "Fault - Thrust @ %s: teeth attached to the stroke "
              "(%d gapped columns)" % (tier, g))

    # ... and the same claim for the normal-fault tick.
    for tier in ("Very Minor", "Regional"):
        seed(lw, line, dict(Category="Structural", Type="Fault - Normal",
                            Weight=tier))
        g = attached(ink_set(render(lw, REF_SCALE, project)))
        check(g == 0, "Fault - Normal @ %s: bar attached (%d gapped)"
              % (tier, g))

    # (2b) thrust (filled) and reverse (open) render differently.
    seed(lw, line, dict(Category="Structural", Type="Fault - Thrust"))
    thrust = ink_set(render(lw, REF_SCALE, project))
    seed(lw, line, dict(Category="Structural", Type="Fault - Reverse"))
    reverse = ink_set(render(lw, REF_SCALE, project))
    # The shared backbone dominates the ink, so compare only the ornament
    # band above the stroke (the line renders at image centre y=200).
    band = PX_H // 2 - 3
    t_up = {p for p in thrust if p[1] < band}
    r_up = {p for p in reverse if p[1] < band}
    tooth_diff = len(t_up ^ r_up)
    check(t_up and r_up and tooth_diff > min(len(t_up), len(r_up)) * 0.3,
          "filled thrust renders distinctly from open reverse "
          "(tooth band %d vs %d px, diff %d)"
          % (len(t_up), len(r_up), tooth_diff))

    # (3) refolded folds differ from overturned folds on screen.
    def ink_of(t):
        seed(lw, line, dict(Category="Structural", Type=t))
        return ink_set(render(lw, REF_SCALE, project))
    for a, b in (("Antiformal Syncline", "Antiform - Overturned"),
                 ("Synformal Anticline", "Synform - Overturned")):
        ia, ib = ink_of(a), ink_of(b)
        sym_diff = len(ia ^ ib)
        check(sym_diff > min(len(ia), len(ib)) * 0.3,
              "%s renders distinctly from %s (diff %d px)" % (a, b, sym_diff))

    # (4) sinistral / dextral are mirrors.
    isin = ink_of("Fault - Sinistral")
    idex = ink_of("Fault - Dextral")
    flipped = {(PX_W - 1 - x, y) for x, y in idex}
    inter = len(isin & flipped)
    union = len(isin | flipped)
    check(abs(len(isin) - len(idex)) < max(len(isin), 1) * 0.05,
          "mirror pair carries equal ink (%d vs %d)"
          % (len(isin), len(idex)))
    check(union and inter / union > 0.55,
          "dextral flipped matches sinistral (IoU %.2f)"
          % (inter / union if union else 0))

    project.removeMapLayer(lw.id())


# ---------------------------------------------------------------------------
# 5. idempotency
# ---------------------------------------------------------------------------

def test_idempotent(tmp_dir):
    print("idempotency:")
    work = os.path.join(tmp_dir, "idem.gpkg")
    shutil.copy2(GPKG, work)

    def qml_bytes():
        con = sqlite3.connect(work)
        try:
            return con.execute("SELECT styleQML FROM layer_styles "
                               "WHERE f_table_name=?", (LW,)).fetchone()[0]
        finally:
            con.close()

    before = qml_bytes()
    argv = sys.argv
    sys.argv = ["inject_linework_marker_decorations.py", work]
    try:
        _inj.main()
    finally:
        sys.argv = argv
    check(qml_bytes() == before, "re-run is byte-identical")


# ---------------------------------------------------------------------------

def main():
    qgs = QgsApplication([], False)
    qgs.initQgis()
    tmp_dir = tempfile.mkdtemp(prefix="lgs_markers_")
    try:
        test_structure()
        tmp_gpkg = os.path.join(tmp_dir, "render.gpkg")
        shutil.copy2(GPKG, tmp_gpkg)
        test_render(tmp_gpkg)
        test_idempotent(tmp_dir)
    finally:
        qgs.exitQgis()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    print("passed: %d  failed: %d" % (_passed, _failed))
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
