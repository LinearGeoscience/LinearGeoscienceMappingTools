#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify vein generations and selvedges (MUST run inside QGIS).

A geometry generator fails SILENTLY.  A typo in the expression, a null that
escapes a guard, a function that does not exist in this QGIS build - none of
them raise, none of them log; the symbol layer simply draws nothing and the
vein comes out bare.  None of that is visible in a diff, so it has to be
caught here.

Covers:

  1. Structure: a selvedge generator on each of the 11 Linework vein symbols
     and each of the 10 Basemap vein categories, found by uuid5 id, carrying
     units=MM, the right SymbolType and a data-defined `enabled`.  The halo
     stroke is NOT the 1.5;0.7 custom dash - that string is the signature
     inject_overlay_alteration_outline.py counts its outlines by, over a
     recursive walk that would see this sub-symbol and mis-count.  And every
     symbol layer owns a data_defined_properties block, because
     inject_weight_scaling finds a layer's block by forward search and would
     otherwise rewrite its neighbour's with the wrong statics.

  2. Expressions parse and evaluate against awkward geometry - straight,
     curved, self-crossing, zero-length lines; large, thin, tiny and
     multipart polygons - producing real geometry where they should and
     NULL (not an error, not the whole polygon) where they cannot.  Note
     this can only test CRS-unit behaviour: QgsExpression evaluates
     $geometry in layer units, whereas the renderer hands the generator
     paper millimetres, so the mm semantics need the render test.

  3. Rendered, at several map scales: the halo appears only when a selvedge
     is recorded, puts no ink at all when it is not, and stays the same size
     on the page as the scale changes - which is what proves units=MM is
     being honoured.  A Basemap polygon too narrow to carry a band degrades
     to nothing drawn rather than flooding solid in the band colour.

  4. Labels: the vein tag composes, and a feature carrying no generation and
     no selvedge labels EXACTLY as it did before this system existed.

  5. QgsExpression construction stays fast.  The parser's cost doubles per
     nested with_variable level, so anyone who "tidies" the flat expressions
     into a with_variable chain trips this.

Usage:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests\\test_vein_selvedge_qgis.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(REPO_ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import importlib  # noqa: E402

from qgis.core import (QgsApplication, QgsExpression,  # noqa: E402
                       QgsExpressionContext, QgsExpressionContextScope,
                       QgsExpressionContextUtils, QgsFeature, QgsGeometry,
                       QgsMapRendererParallelJob, QgsMapSettings, QgsProject,
                       QgsRectangle, QgsVectorLayer)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

_inj = importlib.import_module("inject_vein_generation_selvedge")

GPKG = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
REF_SCALE = 5000
PX_W, PX_H, DPI = 460, 300, 96.0

# One paper millimetre is this many ground metres at the baked reference
# scale, so a feature authored in mm below lands on the page at the size the
# expression constants were tuned for.
M_PER_MM = REF_SCALE / 1000.0

# The flat expressions construct in single-digit ms; one extra
# with_variable level roughly doubles that, so this trips early.
PARSE_BUDGET_MS = 500

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


def style_of(gpkg, layer):
    con = sqlite3.connect("file:%s?mode=ro" % gpkg.replace("\\", "/"), uri=True)
    try:
        row = con.execute("SELECT styleQML FROM layer_styles "
                          "WHERE f_table_name=?", (layer,)).fetchone()
    finally:
        con.close()
    return ET.fromstring(row[0]), row[0]


def label_expr(root):
    return root.find(".//labeling/settings/text-style").get("fieldName")


# ---------------------------------------------------------------------------
# 1. structure
# ---------------------------------------------------------------------------

def test_structure():
    print("structure:")
    for layer, codes, sym_type in (
            (_inj.LW, _inj.LW_VEIN_CODES, "Line"),
            (_inj.BM, list(_inj.VEIN_LITHS), "Fill")):
        root, _ = style_of(GPKG, layer)
        want = {_inj.layer_id("gen", c) for c in codes}
        seen = {}
        for lyr in root.iter("layer"):
            if lyr.get("class") == "GeometryGenerator" and lyr.get("id") in want:
                seen[lyr.get("id")] = lyr
        check(set(seen) == want,
              "%s: %d of %d selvedge generators present"
              % (layer, len(seen), len(want)))
        for lid, lyr in seen.items():
            o = _inj.direct_opts(lyr)
            check(o["units"].get("value") == "MM", "%s %s: units=MM" % (layer, lid))
            check(o["SymbolType"].get("value") == sym_type,
                  "%s %s: SymbolType=%s" % (layer, lid, sym_type))
            check(_inj.get_dd(lyr, "enabled") == _inj.SELVEDGE_ON,
                  "%s %s: data-defined enabled" % (layer, lid))
            check(lyr.get("enabled") == "1",
                  "%s %s: static enabled stays 1 so a dd failure falls back "
                  "to drawing, not to silence" % (layer, lid))

        renderer = root.find(".//renderer-v2")

        # Stack position.  A <symbol> also carries a
        # <data_defined_properties> child, so an off-by-one here buries the
        # Basemap band UNDER its own class fill, where it is drawn over and
        # completely invisible - and every other assertion still passes.
        want_pos = 0 if layer == _inj.LW else 1
        for sym in renderer.find("symbols"):
            for pos, lyr in enumerate(sym.findall("layer")):
                if lyr.get("id") in want:
                    check(pos == want_pos,
                          "%s: selvedge generator sits at stack position %d, "
                          "expected %d - any lower and it is drawn over"
                          % (layer, pos, want_pos))

        for sym in renderer.find("symbols"):
            for lyr in sym.iter("layer"):
                check(lyr.find("data_defined_properties") is not None,
                      "%s: layer %s owns a dd block (inject_weight_scaling "
                      "finds them by forward search)" % (layer, lyr.get("id")))
                if lyr.get("class") != "SimpleLine":
                    continue
                o = _inj.direct_opts(lyr)
                if lyr.get("id") in {_inj.layer_id("stroke", c) for c in codes}:
                    check(o.get("customdash") is None
                          or o["customdash"].get("value") != _inj.ALT_OUTLINE_DASH,
                          "%s: halo stroke avoids the %s alteration-outline "
                          "signature" % (layer, _inj.ALT_OUTLINE_DASH))
                    check(_inj.get_dd(lyr, "outlineStyle") == _inj.CONFIDENCE_DASH,
                          "%s: halo stroke pre-authors outlineStyle so "
                          "inject_confidence_system skips it" % layer)


# ---------------------------------------------------------------------------
# 2. expressions
# ---------------------------------------------------------------------------

LINES = [
    ("straight",   "LINESTRING(0 0, 100 0)", True),
    ("curved",     "LINESTRING(0 0, 40 30, 90 10, 140 60)", True),
    ("selfcross",  "LINESTRING(0 0, 50 50, 50 0, 0 50)", True),
    ("zerolength", "LINESTRING(10 10, 10 10)", False),
    ("duplicated", "LINESTRING(5 5, 5 5, 5 5)", False),
]
POLYS = [
    ("large",     "POLYGON((0 0, 200 0, 200 200, 0 200, 0 0))", True),
    ("thin slab", "POLYGON((0 0, 200 0, 200 1, 0 1, 0 0))", False),
    ("tiny",      "POLYGON((0 0, 0.4 0, 0.4 0.4, 0 0.4, 0 0))", False),
    ("multipart", "MULTIPOLYGON(((0 0, 100 0, 100 100, 0 100, 0 0)),"
                  "((300 0, 300.4 0, 300.4 0.4, 300 0.4, 300 0)))", True),
]


def evaluate(expr, wkt, attrs):
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt(wkt))
    ctx = QgsExpressionContext()
    scope = QgsExpressionContextScope()
    for k, v in attrs.items():
        scope.setVariable(k, v)
    ctx.appendScope(scope)
    e = QgsExpression(expr)
    if e.hasParserError():
        return None, "parse: " + e.parserErrorString()
    e.prepare(ctx)
    ctx.setFeature(f)
    out = e.evaluate(ctx)
    if e.hasEvalError():
        return None, "eval: " + e.evalErrorString()
    return out, None


def is_blank(g):
    return (g is None or not isinstance(g, QgsGeometry)
            or g.isNull() or g.isEmpty())


def generator_exprs(layer, codes):
    """The distinct geometryModifier strings actually shipped."""
    root, _ = style_of(GPKG, layer)
    want = {_inj.layer_id("gen", c) for c in codes}
    out = {}
    for lyr in root.iter("layer"):
        if lyr.get("class") == "GeometryGenerator" and lyr.get("id") in want:
            out[lyr.get("id")] = _inj.direct_opts(lyr)["geometryModifier"].get("value")
    return out


def test_expressions():
    print("expressions:")
    # Fields are unavailable without a layer, so drive the guards through
    # expression variables of the same name via a rewritten expression.
    def as_vars(expr):
        for f in ("Selvedge_cm", "SelvedgeMineral", "Weight", "Category",
                  "Width_cm", "Type"):
            expr = expr.replace('"%s"' % f, "@%s" % f)
        return expr

    lw = sorted(set(generator_exprs(_inj.LW, _inj.LW_VEIN_CODES).values()))
    bm = sorted(set(generator_exprs(_inj.BM, list(_inj.VEIN_LITHS)).values()))
    check(len(bm) == 1, "all 10 Basemap bands share one expression (%d)" % len(bm))
    check(len(lw) == 2, "Linework has 2 expressions - the common one and "
                        "Vein - Shear's cleared offset (%d)" % len(lw))

    for label, exprs, cases in (("halo", lw, LINES), ("band", bm, POLYS)):
        for expr in exprs:
            e = QgsExpression(as_vars(expr))
            check(not e.hasParserError(),
                  "%s parses (%s)" % (label, e.parserErrorString()))
            for name, wkt, should_draw in cases:
                off, err = evaluate(as_vars(expr), wkt,
                                    {"Selvedge_cm": None, "Weight": "Moderate"})
                check(err is None, "%s on %s (no selvedge): %s" % (label, name, err))
                check(is_blank(off),
                      "%s on %s draws nothing when no selvedge is recorded"
                      % (label, name))

                on, err = evaluate(as_vars(expr), wkt,
                                   {"Selvedge_cm": 5.0, "Weight": "Moderate"})
                if not check(err is None, "%s on %s: %s" % (label, name, err)):
                    continue
                if should_draw:
                    check(not is_blank(on), "%s on %s produces geometry" % (label, name))
                    if label == "band" and not is_blank(on):
                        whole = QgsGeometry.fromWkt(wkt).area()
                        check(on.area() < 0.9 * whole,
                              "%s on %s is a margin, not the whole polygon "
                              "(%.0f%%)" % (label, name, 100 * on.area() / whole))
                else:
                    check(is_blank(on),
                          "%s on %s degrades to nothing rather than to a mess"
                          % (label, name))


def test_parse_budget():
    print("parse budget:")
    exprs = dict(generator_exprs(_inj.LW, _inj.LW_VEIN_CODES))
    exprs.update(generator_exprs(_inj.BM, list(_inj.VEIN_LITHS)))
    worst = 0.0
    for expr in set(exprs.values()):
        t = time.time()
        QgsExpression(expr).hasParserError()
        worst = max(worst, (time.time() - t) * 1000)
    check(worst < PARSE_BUDGET_MS,
          "slowest generator constructs in %.0f ms (budget %d ms - if this "
          "fails, someone nested the expression in with_variable)"
          % (worst, PARSE_BUDGET_MS))


# ---------------------------------------------------------------------------
# 3. it actually draws
# ---------------------------------------------------------------------------

def render(lyr, scale, project):
    gw = PX_W / DPI * 0.0254 * scale
    gh = PX_H / DPI * 0.0254 * scale
    c = lyr.extent().center()
    ms = QgsMapSettings()
    ms.setOutputSize(QSize(PX_W, PX_H))
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


def ink(img):
    return sum(1 for y in range(PX_H) for x in range(PX_W)
               if QColor(img.pixel(x, y)).lightness() < 235)


def near(img, rgb, tol=18):
    """Pixels within tol of one colour.

    The band is the unit's own fill deepened 25%, so it is dark on dark: a
    plain ink count cannot see it appear, because the pixels it lands on
    were already counted.  Only a colour census can.
    """
    r0, g0, b0 = rgb
    n = 0
    for y in range(PX_H):
        for x in range(PX_W):
            c = QColor(img.pixel(x, y))
            if (abs(c.red() - r0) <= tol and abs(c.green() - g0) <= tol
                    and abs(c.blue() - b0) <= tol):
                n += 1
    return n


def band_colour(code):
    """What convert_basemap() would have written for this category."""
    root, _ = style_of(GPKG, _inj.BM)
    renderer = root.find(".//renderer-v2")
    sym_name = {c.get("value"): c.get("symbol")
                for c in renderer.find("categories")}[code]
    for sym in renderer.find("symbols"):
        if sym.get("name") != sym_name:
            continue
        for lyr in sym.findall("layer"):
            if lyr.get("class") == "SimpleFill":
                raw = _inj.direct_opts(lyr)["color"].get("value")
                return tuple(int(v) for v in _inj.rgba(
                    raw, alpha="255", scale=_inj.BAND_DARKEN).split(",")[:3])
    raise AssertionError("no SimpleFill on %s" % code)


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
    k = scale / 1000.0
    return "LINESTRING(0 0, %f 0)" % (length_mm * k)


def mm_box(w_mm, h_mm, scale=REF_SCALE):
    k = scale / 1000.0
    w, h = w_mm * k, h_mm * k
    return ("POLYGON((0 0, %f 0, %f %f, 0 %f, 0 0))" % (w, w, h, h))


def test_render(tmp_gpkg):
    print("render:")
    project = QgsProject.instance()

    lw = QgsVectorLayer("%s|layername=%s" % (tmp_gpkg, _inj.LW), "lw", "ogr")
    bm = QgsVectorLayer("%s|layername=%s" % (tmp_gpkg, _inj.BM), "bm", "ogr")
    if not check(lw.isValid() and bm.isValid(), "both layers open"):
        return
    for lyr in (lw, bm):
        project.addMapLayer(lyr)
        lyr.setLabelsEnabled(False)      # labels would count as ink

    # --- Linework halo -------------------------------------------------
    base = dict(Category="Veins", Type="Vein - Quartz", Weight="Moderate",
                Width_cm=7.0)

    # Symbology carries a reference scale, so a symbol keeps its GROUND size
    # and zooms with the map.  The claim under test is therefore not "the
    # same page size at every map scale" - it is "the authored page size at
    # whatever scale the project is set to", which is what Set Mapping Scale
    # rewrites the reference scale for.  So move the reference scale, the
    # map scale and the feature's ground size together: the picture must
    # come out identical every time.
    extra = {}
    for scale in (500, REF_SCALE, 20000):
        lw.renderer().setReferenceScale(scale)
        seed(lw, mm_line(40, scale), base)
        off = ink(render(lw, scale, project))
        seed(lw, mm_line(40, scale),
             dict(base, Selvedge_cm=5.0, SelvedgeMineral="Bt"))
        on = ink(render(lw, scale, project))
        extra[scale] = on - off
        check(on > off, "halo puts ink down at 1:%d (%d -> %d px)"
              % (scale, off, on))
    lw.renderer().setReferenceScale(REF_SCALE)
    print("    halo extra ink: "
          + "  ".join("1:%d=%d" % (s, v) for s, v in sorted(extra.items())))
    lo, hi = min(extra.values()), max(extra.values())
    check(hi and (hi - lo) <= 0.15 * hi,
          "halo is the authored page size at 1:500, 1:5000 and 1:20000 "
          "(%d..%d px) - this is what proves units=MM" % (lo, hi))

    # A selvedge on a vein type that deliberately has no halo must stay
    # quiet rather than half-draw.
    seed(lw, mm_line(40), dict(base, Type="Vein Set / Sheeted"))
    off = ink(render(lw, REF_SCALE, project))
    seed(lw, mm_line(40), dict(base, Type="Vein Set / Sheeted",
                               Selvedge_cm=5.0))
    check(ink(render(lw, REF_SCALE, project)) == off,
          "Vein Set / Sheeted is untouched by a recorded selvedge")

    # --- Basemap band --------------------------------------------------
    rgb = band_colour("VQ")
    for name, wkt, should_band in (("wide", mm_box(30, 30), True),
                                   ("hairline", mm_box(30, 0.5), False)):
        seed(bm, wkt, dict(Lithology1="VQ"))
        off = near(render(bm, REF_SCALE, project), rgb)
        seed(bm, wkt, dict(Lithology1="VQ", Selvedge_cm=5.0,
                           SelvedgeMineral="Bt"))
        img = render(bm, REF_SCALE, project)
        on = near(img, rgb)
        whole = ink(img)
        if should_band:
            # A real hem, not the handful of antialiased pixels the dashed
            # boundary throws off: a 0.7 mm band round a 30 mm box at this
            # DPI is several hundred px.  `on > off` alone passed while the
            # band was buried under the class fill.
            check(on - off > 200,
                  "%s vein polygon grows a real band (%d -> %d band px)"
                  % (name, off, on))
            check(whole and on < 0.5 * whole,
                  "%s band hems the margin rather than flooding the unit "
                  "(%d of %d px)" % (name, on, whole))
        else:
            check(on == off,
                  "%s vein polygon degrades to nothing rather than flooding "
                  "solid in the band colour (%d -> %d band px)"
                  % (name, off, on))

    for lyr in (lw, bm):
        project.removeMapLayer(lyr.id())


# ---------------------------------------------------------------------------
# 4. labels
# ---------------------------------------------------------------------------

def eval_label(expr, lyr, wkt, attrs):
    f = QgsFeature(lyr.fields())
    f.setGeometry(QgsGeometry.fromWkt(wkt))
    for k, v in attrs.items():
        f[k] = v
    ctx = QgsExpressionContext()
    scope = QgsExpressionContextScope()
    scope.setFeature(f)
    scope.setFields(lyr.fields())
    ctx.appendScope(scope)
    e = QgsExpression(expr)
    e.prepare(ctx)
    return e.evaluate(ctx)


def test_labels(tmp_gpkg):
    print("labels:")
    lw = QgsVectorLayer("%s|layername=%s" % (tmp_gpkg, _inj.LW), "lw", "ogr")
    bm = QgsVectorLayer("%s|layername=%s" % (tmp_gpkg, _inj.BM), "bm", "ogr")
    lw_expr = label_expr(style_of(GPKG, _inj.LW)[0])
    bm_expr = label_expr(style_of(GPKG, _inj.BM)[0])
    check(_inj.LW_GEN_TEXT in lw_expr, "Linework label carries the generation")
    check(_inj.LW_SLV_TEXT in lw_expr, "Linework label carries the selvedge")
    check(_inj.BM_TAG in bm_expr, "Basemap label carries the vein tag")

    LINE = "LINESTRING(0 0, 10 0)"
    POLY = "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"
    got = eval_label(lw_expr, lw, LINE, dict(
        Category="Veins", Type="Vein - Quartz", VeinGen="V2", Width_cm=7.0,
        Mineral1="Qz", Mineral1Pct=10, Mineral2="Py", Selvedge_cm=3.0,
        SelvedgeMineral="Bt"))
    check(got == "V2 7cm Qz10%-Py slv 3cm Bt",
          "Linework vein tag composes generation-first: %r" % got)

    got = eval_label(lw_expr, lw, LINE, dict(
        Category="Veins", Type="Vein", VeinGen="V1", SelvedgeMineral="Ser"))
    check(got == "V1 slv Ser",
          "a selvedge mineral with no measured width still labels: %r" % got)

    # The gate is not belt-and-braces: a stray Selvedge_cm on a fault would
    # otherwise print a selvedge the symbology never draws.
    got = eval_label(lw_expr, lw, LINE, dict(
        Category="Structural", Type="Fault", Label="F1", VeinGen="V2",
        Selvedge_cm=9.0))
    check(got == "F1", "a non-vein ignores stray vein data: %r" % got)

    got = eval_label(bm_expr, bm, POLY, dict(
        Lithology1="VQ", VeinGen="V2", Selvedge_cm=3.0, SelvedgeMineral="Bt"))
    check("V2 slv 3cm Bt" in got and "font-weight:400" in got,
          "Basemap vein tag rides in the light span: %r" % got)
    got = eval_label(bm_expr, bm, POLY, dict(
        Lithology1="FGR", VeinGen="V2", Selvedge_cm=3.0))
    check("V2" not in got, "a non-vein lithology ignores stray vein data: %r" % got)

    # Nothing recorded must label EXACTLY as it did before this existed.
    for lyr, expr, wkt, attrs, want in (
            (lw, lw_expr, LINE, dict(Category="Veins", Type="Vein - Quartz",
                                     Width_cm=7.0, Mineral1="Qz"), "7cm Qz"),
            (lw, lw_expr, LINE, dict(Category="Structural", Type="Fault",
                                     Label="F1"), "F1"),
            (bm, bm_expr, POLY, dict(Lithology1="VQ"),
             '<div style="font-weight:600;">VQ</div>')):
        got = eval_label(expr, lyr, wkt, attrs)
        check(got == want, "untagged feature labels unchanged: %r != %r"
              % (got, want))


# ---------------------------------------------------------------------------

def main():
    if not os.path.exists(GPKG):
        print("template not found: %s" % GPKG)
        return 2
    qgs = QgsApplication([], False)
    qgs.initQgis()
    tmp = tempfile.mkdtemp(prefix="lgs-selvedge-")
    try:
        work = os.path.join(tmp, "t.gpkg").replace("\\", "/")
        shutil.copy2(GPKG, work)
        test_structure()
        test_expressions()
        test_parse_budget()
        test_render(work)
        test_labels(work)
    finally:
        QgsProject.instance().removeAllMapLayers()
        qgs.exitQgis()
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
