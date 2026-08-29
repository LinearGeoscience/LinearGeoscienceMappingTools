"""Dash patterns scale with the Weight tier, and Moderate keeps the authored look.

inject_dash_weight_scaling.py bakes a Weight CASE onto every dash-bearing
Linework stroke (62 static dashes + 32 confidence flips).  A wrong dd
expression fails silently - the stroke just draws solid or vanishes - so
this test proves the claims off-line and in pixels:

  1. structure: exactly 94 dash-bearing strokes, every customDash names
     Weight, every ELSE mirrors the layer's authored customdash static;
  2. every customDash expression parses and, evaluated per tier x
     Confidence, returns the authored dash scaled element-wise by
     exactly the inject_weight_scaling FACTORS (Moderate/NULL -> x1);
  3. rendered: a static-dash code and a confidence-flipped code both
     draw LONGER, FEWER dashes at Regional and shorter, more numerous
     dashes at Very Minor (ink run-length along the line);
  4. idempotency: a re-run is byte-identical, and retuning a static
     customdash then re-running refreshes that layer's ramp (the
     rebuild-from-statics contract).

Run under the QGIS python:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests\\test_dash_scaling_qgis.py
"""

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

from qgis.core import (QgsApplication, QgsExpression,  # noqa: E402
                       QgsExpressionContext, QgsExpressionContextScope,
                       QgsExpressionContextUtils, QgsFeature, QgsGeometry,
                       QgsMapRendererParallelJob, QgsMapSettings, QgsProject,
                       QgsRectangle, QgsVectorLayer)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

_inj = importlib.import_module("inject_dash_weight_scaling")
from inject_weight_scaling import FACTORS  # noqa: E402

GPKG = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
LW = _inj.LW
REF_SCALE = 5000
PX_W, PX_H, DPI = 1280, 200, 192.0  # 2x DPI: a Very Minor 0.68 pt line must survive the ink threshold

TIERS = dict(FACTORS, Moderate="1")

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


def qml_text(gpkg):
    con = sqlite3.connect("file:%s?mode=ro" % gpkg.replace("\\", "/"),
                          uri=True)
    try:
        return con.execute("SELECT styleQML FROM layer_styles "
                           "WHERE f_table_name=?", (LW,)).fetchone()[0]
    finally:
        con.close()


def dash_layers(qml):
    """[(customdash static, customDash expression, is_flip)] via the
    injector's own iteration, so the test sees what the injector sees."""
    renderer = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S).group(0)
    out = []
    for s, e in _inj.simpleline_layers(renderer):
        lx = renderer[s:e]
        dd = _inj.dd_expressions(lx)
        val = _inj.statics_of(lx)
        custom = dd.get("customDash")
        if custom is None and val("use_custom_dash") != "1":
            continue
        out.append((val("customdash"), custom,
                    custom is not None and _inj.MEGA_DASH in custom))
    return out


# ---------------------------------------------------------------------------
# 1. structure
# ---------------------------------------------------------------------------

def test_structure():
    print("structure:")
    layers = dash_layers(qml_text(GPKG))
    flips = [l for l in layers if l[2]]
    statics = [l for l in layers if not l[2]]
    check(len(statics) == _inj.EXPECT_STATIC,
          "%d static dashes (got %d)" % (_inj.EXPECT_STATIC, len(statics)))
    check(len(flips) == _inj.EXPECT_FLIPS,
          "%d confidence flips (got %d)" % (_inj.EXPECT_FLIPS, len(flips)))
    check(all(c is not None and '"Weight"' in c for _, c, _f in layers),
          "every dash-bearing stroke carries a Weight customDash")
    check(all(a and c == (_inj.flip_weight_case(a) if f
                          else _inj.dash_weight_case(a))
              for a, c, f in layers),
          "every expression is the injector's own text for its static")
    check(all(("ELSE '%s' END" % a) in c for a, c, _f in layers),
          "every ELSE mirrors the authored dash (Moderate/NULL untouched)")


# ---------------------------------------------------------------------------
# 2. expressions parse and evaluate to scaled dashes
# ---------------------------------------------------------------------------

def evaluate(expr, attrs):
    ctx = QgsExpressionContext()
    scope = QgsExpressionContextScope()
    for k, v in attrs.items():
        scope.setVariable(k, v)
    ctx.appendScope(scope)
    e = QgsExpression(expr)
    if e.hasParserError():
        return None, "parse: " + e.parserErrorString()
    # evaluate against a bare feature carrying the attributes
    from qgis.core import QgsFields, QgsField
    from qgis.PyQt.QtCore import QMetaType
    fields = QgsFields()
    for k in attrs:
        fields.append(QgsField(k, QMetaType.Type.QString))
    f = QgsFeature(fields)
    for k, v in attrs.items():
        f[k] = v
    ctx.setFeature(f)
    out = e.evaluate(ctx)
    if e.hasEvalError():
        return None, "eval: " + e.evalErrorString()
    return out, None


def test_expressions():
    print("expressions:")
    layers = dash_layers(qml_text(GPKG))
    bad_parse = mismatch = 0
    for authored, expr, is_flip in layers:
        if QgsExpression(expr).hasParserError():
            bad_parse += 1
            continue
        for tier, factor in TIERS.items():
            expect = _inj.scaled_dash(authored, float(factor))
            conf = "Inferred" if is_flip else "Observed"
            got, err = evaluate(expr, {"Weight": tier, "Confidence": conf})
            if err or got != expect:
                mismatch += 1
                print("    %s @ %s/%s: got %r want %r (%s)"
                      % (authored, tier, conf, got, expect, err))
        if is_flip:
            got, err = evaluate(expr, {"Weight": "Regional",
                                       "Confidence": "Observed"})
            if err or got != _inj.MEGA_DASH:
                mismatch += 1
                print("    flip %s Observed: got %r want MEGA_DASH (%s)"
                      % (authored, got, err))
    check(bad_parse == 0, "all customDash expressions parse (%d bad)"
          % bad_parse)
    check(mismatch == 0, "every tier evaluates to the exact scaled dash "
          "(%d mismatches)" % mismatch)


# ---------------------------------------------------------------------------
# 3. rendered
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
    return (c.red() + c.green() + c.blue()) / 3 < 120


def dash_runs(img):
    """Number of ink runs along the line's axis (any inky pixel per column)."""
    cols = [any(inky(QColor(img.pixel(x, y))) for y in range(PX_H))
            for x in range(PX_W)]
    runs = 0
    prev = False
    for c in cols:
        if c and not prev:
            runs += 1
        prev = c
    return runs, sum(cols)


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


def test_render(tmp_gpkg):
    print("render:")
    project = QgsProject.instance()
    lw = QgsVectorLayer("%s|layername=%s" % (tmp_gpkg, LW), "lw", "ogr")
    if not check(lw.isValid(), "Linework opens"):
        return
    project.addMapLayer(lw)
    lw.setLabelsEnabled(False)
    lw.renderer().setReferenceScale(REF_SCALE)

    line = mm_line(150)

    # A static-dash code: Fault - Inferred (15;7 authored).
    runs = {}
    for tier in ("Very Minor", "Moderate", "Regional"):
        seed(lw, line, dict(Category="Structural", Type="Fault - Inferred",
                            Weight=tier))
        runs[tier], ink = dash_runs(render(lw, REF_SCALE, project))
        check(runs[tier] > 1, "Fault - Inferred @ %s draws a dashed line "
              "(%d runs, %d ink cols)" % (tier, runs[tier], ink))
    check(runs["Regional"] < runs["Moderate"] < runs["Very Minor"],
          "static dash count falls as Weight rises (VM %d > Mod %d > Reg %d)"
          % (runs["Very Minor"], runs["Moderate"], runs["Regional"]))

    # A confidence-flipped code: Fault, Inferred (38;7 authored).
    runs = {}
    for tier in ("Very Minor", "Moderate", "Regional"):
        seed(lw, line, dict(Category="Structural", Type="Fault",
                            Confidence="Inferred", Weight=tier))
        runs[tier], ink = dash_runs(render(lw, REF_SCALE, project))
        check(runs[tier] > 1, "Fault/Inferred @ %s draws a dashed line "
              "(%d runs, %d ink cols)" % (tier, runs[tier], ink))
    check(runs["Regional"] < runs["Moderate"] < runs["Very Minor"],
          "flip dash count falls as Weight rises (VM %d > Mod %d > Reg %d)"
          % (runs["Very Minor"], runs["Moderate"], runs["Regional"]))

    # Observed stays effectively solid at any tier (the mega-dash).
    seed(lw, line, dict(Category="Structural", Type="Fault",
                        Confidence="Observed", Weight="Regional"))
    solid_runs, _ = dash_runs(render(lw, REF_SCALE, project))
    check(solid_runs == 1, "Fault/Observed @ Regional renders solid "
          "(%d runs)" % solid_runs)

    project.removeMapLayer(lw.id())


# ---------------------------------------------------------------------------
# 4. idempotency + rebuild-from-statics
# ---------------------------------------------------------------------------

def run_injector(gpkg):
    argv = sys.argv
    sys.argv = ["inject_dash_weight_scaling.py", gpkg]
    try:
        _inj.main()
    finally:
        sys.argv = argv


def test_idempotent(tmp_dir):
    print("idempotency:")
    work = os.path.join(tmp_dir, "idem.gpkg")
    shutil.copy2(GPKG, work)
    before = qml_text(work)
    run_injector(work)
    check(qml_text(work) == before, "re-run is byte-identical")

    # Retune one static customdash and re-run: that ramp must refresh.
    con = sqlite3.connect(work)
    qml = con.execute("SELECT styleQML FROM layer_styles WHERE "
                      "f_table_name=?", (LW,)).fetchone()[0]
    tuned = qml.replace('name="customdash" type="QString" value="15;7"',
                        'name="customdash" type="QString" value="16;8"', 1)
    check(tuned != qml, "found a 15;7 static to retune")
    con.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (tuned, LW))
    con.commit()
    con.close()
    run_injector(work)
    refreshed = qml_text(work)
    esc = _inj.dash_weight_case("16;8").replace("&", "&amp;") \
                                       .replace("<", "&lt;") \
                                       .replace(">", "&gt;") \
                                       .replace('"', "&quot;")
    check(esc in refreshed,
          "retuned static got a rebuilt ramp (16;8 branches present)")
    try:
        ET.fromstring(refreshed)
        check(True, "refreshed QML parses")
    except ET.ParseError as exc:
        check(False, "refreshed QML parses (%s)" % exc)


# ---------------------------------------------------------------------------

def main():
    global _passed, _failed
    qgs = QgsApplication([], False)
    qgs.initQgis()
    tmp_dir = tempfile.mkdtemp(prefix="lgs_dash_")
    try:
        test_structure()
        test_expressions()
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
