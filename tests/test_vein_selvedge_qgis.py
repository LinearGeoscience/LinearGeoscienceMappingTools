#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify vein generations, dotted selvedges and the label repeat.

MUST run inside QGIS.

Two whole classes of failure here are SILENT, and both have actually
happened:

  * A geometry generator that draws nothing.  A typo in the expression, a
    null that escapes a guard, a function that does not exist in this build
    - none of them raise, none of them log; the symbol layer simply draws
    nothing and the vein comes out bare.
  * A data-defined expression that does not PARSE.  QGIS drops it without a
    word and the layer keeps its static value, so the selvedge dots render
    in the fallback colour and every structural assertion still passes.
    That is exactly how a five-argument color_rgba() shipped once.

Hence test_dd_expressions_parse, which is the cheapest and most valuable
check in this file.

Covers:

  1. Structure: three ring generators on each vein symbol, found by uuid5
     id, at the right stack positions, carrying units=MM, SymbolType=Line, a
     per-ring data-defined `enabled`, and a MarkerLine of dots whose colour
     is data-defined from SelvedgeMineral.  No round-1 solid halo survives.
  2. EVERY data-defined expression on those layers parses.
  3. The generator expressions evaluate over awkward geometry - straight,
     curved, self-crossing, zero-length lines; large, thin, tiny and
     multipart polygons - producing real geometry where they should and
     NULL where they cannot.  Note this can only test CRS-unit behaviour:
     QgsExpression evaluates $geometry in layer units, whereas the renderer
     hands the generator paper millimetres, so mm semantics need the render
     test.
  4. Rendered: rings appear only when a selvedge is recorded, one more ring
     per width tier, the stipple keeps its size across map scales, dots take
     the mineral's colour, Basemap rings land OUTSIDE the polygon, and a pod
     too small to hem degrades rather than flooding.
  5. Labels: the vein tag composes, and a feature carrying no generation and
     no selvedge labels EXACTLY as it did before this system existed.
  6. The Linework label repeat is held in MAP UNITS and agrees with
     script_setmapping - a millimetre repeat is paper-at-the-render-scale,
     so it put a label every 8 m of ground at 1:1000.
  7. QgsExpression construction stays fast.

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
PARENT = os.path.dirname(REPO_ROOT)
for _p in (os.path.join(REPO_ROOT, "scripts"), PARENT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
PKG = os.path.basename(REPO_ROOT)

import importlib  # noqa: E402

from qgis.core import (QgsApplication, QgsExpression,  # noqa: E402
                       QgsExpressionContext, QgsExpressionContextScope,
                       QgsExpressionContextUtils, QgsFeature, QgsGeometry,
                       QgsMapRendererParallelJob, QgsMapSettings, QgsProject,
                       QgsRectangle, QgsVectorLayer)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

_inj = importlib.import_module("inject_vein_generation_selvedge")
_cartography = importlib.import_module("inject_label_cartography")
_setmapping = importlib.import_module(PKG + ".script_setmapping")

GPKG = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
REF_SCALE = 5000
PX_W, PX_H, DPI = 460, 300, 96.0

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
    return ET.fromstring(row[0])


def label_expr(root):
    return root.find(".//labeling/settings/text-style").get("fieldName")


LAYERS = ((_inj.LW, _inj.LW_VEIN_CODES), (_inj.BM, list(_inj.VEIN_LITHS)))


def ring_layers(root, codes):
    """{(code, ring): <layer>} for the selvedge generators."""
    want = {_inj.layer_id("ring%d" % r, c): (c, r)
            for c in codes for r in _inj.RINGS}
    out = {}
    for lyr in root.iter("layer"):
        key = want.get(lyr.get("id"))
        if key and lyr.get("class") == "GeometryGenerator":
            out[key] = lyr
    return out


# ---------------------------------------------------------------------------
# 1. structure
# ---------------------------------------------------------------------------

def test_structure():
    print("structure:")
    for layer, codes in LAYERS:
        root = style_of(GPKG, layer)
        rings = ring_layers(root, codes)
        check(len(rings) == len(codes) * len(_inj.RINGS),
              "%s: %d of %d ring generators present"
              % (layer, len(rings), len(codes) * len(_inj.RINGS)))

        for (code, ring), lyr in sorted(rings.items()):
            where = "%s %s ring %d" % (layer, code, ring)
            o = _inj.direct_opts(lyr)
            check(o["units"].get("value") == "MM", where + ": units=MM")
            check(o["SymbolType"].get("value") == "Line",
                  where + ": SymbolType=Line")
            check(_inj.get_dd(lyr, "enabled") == _inj.RING_ON[ring],
                  where + ": per-ring data-defined enabled")
            check(lyr.get("enabled") == "1",
                  where + ": static enabled stays 1, so a dd failure falls "
                          "back to drawing rather than to silence")
            ml = lyr.find("symbol/layer")
            check(ml is not None and ml.get("class") == "MarkerLine",
                  where + ": sub-symbol is a MarkerLine")
            if ml is None:
                continue
            phase = _inj.direct_opts(ml).get("offset_along_line")
            check(phase is not None
                  and float(phase.get("value")) == _inj.DOT_PHASE[ring],
                  where + ": dots are phased, so the rings interleave")
            dot = ml.find("symbol/layer")
            check(dot is not None and dot.get("class") == "SimpleMarker",
                  where + ": the MarkerLine carries a dot")
            if dot is None:
                continue
            check("SelvedgeMineral" in (_inj.get_dd(dot, "fillColor") or ""),
                  where + ": dot colour follows the recorded mineral")
            # inject_overlay_alteration_outline counts its outlines by this
            # dash over a recursive walk that would see this sub-symbol.
            for opt in lyr.iter("Option"):
                if opt.get("name") == "customdash":
                    check(opt.get("value") != _inj.ALT_OUTLINE_DASH,
                          where + ": avoids the alteration-outline dash")

        # Stack position, and no round-1 survivor.
        base = 0 if layer == _inj.LW else 1
        renderer = root.find(".//renderer-v2")
        by_id = {_inj.layer_id("ring%d" % r, c): r
                 for c in codes for r in _inj.RINGS}
        for sym in renderer.find("symbols"):
            for pos, lyr in enumerate(sym.findall("layer")):
                r = by_id.get(lyr.get("id"))
                if r is None:
                    continue
                want_pos = base + _inj.RINGS.index(r)
                check(pos == want_pos,
                      "%s: ring %d sits at stack position %d, expected %d - "
                      "any lower and it is drawn over"
                      % (layer, r, pos, want_pos))
        old = {_inj.layer_id("gen", c) for c in codes}
        check(not any(l.get("id") in old for l in root.iter("layer")),
              "%s: no round-1 solid selvedge survived alongside the rings"
              % layer)

        # Every layer owns a dd block, or inject_weight_scaling finds its
        # neighbour's by forward search and rewrites it with wrong statics.
        for sym in renderer.find("symbols"):
            for lyr in sym.iter("layer"):
                check(lyr.find("data_defined_properties") is not None,
                      "%s: layer %s owns a dd block" % (layer, lyr.get("id")))


def test_retired_codes():
    print("retired codes:")
    con = sqlite3.connect("file:%s?mode=ro" % GPKG.replace("\\", "/"), uri=True)
    try:
        rows = {c for (c,) in con.execute(
            "SELECT Code FROM LineworkCodes WHERE Type='Veins'")}
    finally:
        con.close()
    for gone in ("Vein - Epidote", "Vein - Mineralised"):
        check(gone not in rows, "%s is out of LineworkCodes" % gone)
    check(set(_inj.LW_VEIN_CODES) <= rows,
          "every LW_VEIN_CODES entry still exists (%s)"
          % sorted(set(_inj.LW_VEIN_CODES) - rows))

    confidence = importlib.import_module("inject_confidence_system")
    veins = [c for c in confidence.SOLID_CODES if c.startswith("Vein")]
    check(sorted(veins) == sorted(_inj.LW_VEIN_CODES),
          "inject_confidence_system.SOLID_CODES tracks LW_VEIN_CODES")


# ---------------------------------------------------------------------------
# 2. every data-defined expression parses
# ---------------------------------------------------------------------------

def test_dd_expressions_parse():
    """The cheapest check here, and the one that catches the silent killer.

    QGIS drops an unparseable data-defined expression without a word: the
    layer keeps its static value and everything else still looks right.
    """
    print("dd expressions parse:")
    for layer, codes in LAYERS:
        root = style_of(GPKG, layer)
        n = 0
        for (code, ring), gen in sorted(ring_layers(root, codes).items()):
            for lyr in [gen] + list(gen.iter("layer")):
                dd = lyr.find("data_defined_properties")
                if dd is None:
                    continue
                for opt in dd.iter("Option"):
                    if opt.get("name") != "expression":
                        continue
                    expr = opt.get("value") or ""
                    if not expr:
                        continue
                    n += 1
                    e = QgsExpression(expr)
                    check(not e.hasParserError(),
                          "%s %s ring %d: a dd expression does not parse (%s) "
                          "- QGIS would ignore it in silence: %s"
                          % (layer, code, ring, e.parserErrorString(),
                             expr[:90]))
            expr = _inj.direct_opts(gen)["geometryModifier"].get("value")
            e = QgsExpression(expr)
            check(not e.hasParserError(),
                  "%s %s ring %d: geometryModifier does not parse (%s)"
                  % (layer, code, ring, e.parserErrorString()))
        check(n > 0, "%s: found dd expressions to check (%d)" % (layer, n))


# ---------------------------------------------------------------------------
# 3. expressions over awkward geometry
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
    ("thin slab", "POLYGON((0 0, 200 0, 200 1, 0 1, 0 0))", True),
    ("tiny",      "POLYGON((0 0, 0.4 0, 0.4 0.4, 0 0.4, 0 0))", True),
    ("multipart", "MULTIPOLYGON(((0 0, 100 0, 100 100, 0 100, 0 0)),"
                  "((300 0, 300.4 0, 300.4 0.4, 300 0.4, 300 0)))", True),
]


def as_vars(expr):
    """Fields are unavailable without a layer; drive the guards through
    same-named expression variables instead."""
    for f in ("Selvedge_cm", "SelvedgeMineral", "Weight", "Category",
              "Width_cm", "Type"):
        expr = expr.replace('"%s"' % f, "@%s" % f)
    return expr


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


def test_expressions():
    print("expressions:")
    for layer, codes, cases in ((_inj.LW, _inj.LW_VEIN_CODES, LINES),
                                (_inj.BM, list(_inj.VEIN_LITHS), POLYS)):
        root = style_of(GPKG, layer)
        seen = set()
        for (code, ring), gen in sorted(ring_layers(root, codes).items()):
            expr = as_vars(
                _inj.direct_opts(gen)["geometryModifier"].get("value"))
            if expr in seen:
                continue
            seen.add(expr)
            for name, wkt, should_draw in cases:
                off, err = evaluate(expr, wkt, {"Selvedge_cm": None,
                                                "Weight": "Moderate"})
                check(err is None, "%s ring %d on %s (no selvedge): %s"
                      % (layer, ring, name, err))
                check(is_blank(off),
                      "%s ring %d on %s draws nothing with no selvedge "
                      "recorded" % (layer, ring, name))

                on, err = evaluate(expr, wkt, {"Selvedge_cm": 30.0,
                                               "Weight": "Moderate"})
                if not check(err is None, "%s ring %d on %s: %s"
                             % (layer, ring, name, err)):
                    continue
                if should_draw:
                    check(not is_blank(on),
                          "%s ring %d on %s produces geometry"
                          % (layer, ring, name))
                else:
                    check(is_blank(on),
                          "%s ring %d on %s degrades to nothing rather than "
                          "to a mess" % (layer, ring, name))
        check(len(seen) <= 2 * len(_inj.RINGS),
              "%s: one expression per ring, plus the Vein - Shear clearance "
              "variant (%d)" % (layer, len(seen)))


def test_parse_budget():
    print("parse budget:")
    worst = 0.0
    for layer, codes in LAYERS:
        root = style_of(GPKG, layer)
        for gen in ring_layers(root, codes).values():
            expr = _inj.direct_opts(gen)["geometryModifier"].get("value")
            t = time.time()
            QgsExpression(expr).hasParserError()
            worst = max(worst, (time.time() - t) * 1000)
    check(worst < PARSE_BUDGET_MS,
          "slowest generator constructs in %.0f ms (budget %d ms - if this "
          "fails, someone nested the expression in with_variable)"
          % (worst, PARSE_BUDGET_MS))


# ---------------------------------------------------------------------------
# 4. it actually draws
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


def ink(img):
    return sum(1 for y in range(PX_H) for x in range(PX_W)
               if QColor(img.pixel(x, y)).lightness() < 235)


def near(img, rgb, tol=22):
    """Pixels within tol of one colour.

    A plain ink count cannot see a recoloured dot - the pixel was already
    counted - so mineral colour needs a census.
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


def composite(rgb, alpha):
    """What an alpha-blended dot colour becomes over white."""
    a = alpha / 255.0
    return tuple(int(round(c * a + 255 * (1 - a))) for c in rgb)


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


def mm_box(w_mm, h_mm, scale=REF_SCALE):
    k = scale / 1000.0
    w, h = w_mm * k, h_mm * k
    return "POLYGON((0 0, %f 0, %f %f, 0 %f, 0 0))" % (w, w, h, h)


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

    base = dict(Category="Veins", Type="Vein - Quartz", Weight="Moderate",
                Width_cm=7.0)

    seed(lw, mm_line(40), base)
    bare = ink(render(lw, REF_SCALE, project))
    steps = []
    for slv in (1.0, 5.0, 30.0):
        seed(lw, mm_line(40), dict(base, Selvedge_cm=slv))
        steps.append(ink(render(lw, REF_SCALE, project)) - bare)
    print("    stipple ink by tier: 1cm=%d  5cm=%d  30cm=%d" % tuple(steps))
    check(steps[0] > 0, "a 1 cm selvedge puts a ring down (%d px)" % steps[0])
    check(steps[1] > steps[0] and steps[2] > steps[1],
          "each width tier adds a ring (%s)" % (steps,))

    seed(lw, mm_line(40), dict(base, Selvedge_cm=0.0))
    check(ink(render(lw, REF_SCALE, project)) == bare,
          "a zero width reads as unrecorded, not as a zero-wide selvedge")

    seed(lw, mm_line(40), dict(base, SelvedgeMineral="Bt"))
    check(ink(render(lw, REF_SCALE, project)) > bare,
          "a mineral recorded without a width still draws ring 1")

    # Symbology carries a reference scale, so a symbol keeps its GROUND size
    # and zooms with the map.  The claim is "the authored page size at
    # whatever scale the project is set to", which is what Set Mapping Scale
    # rewrites the reference scale for - so move the reference scale, the map
    # scale and the feature's ground size together.
    extra = {}
    for scale in (500, REF_SCALE, 20000):
        lw.renderer().setReferenceScale(scale)
        seed(lw, mm_line(40, scale), base)
        off = ink(render(lw, scale, project))
        seed(lw, mm_line(40, scale), dict(base, Selvedge_cm=30.0))
        extra[scale] = ink(render(lw, scale, project)) - off
    lw.renderer().setReferenceScale(REF_SCALE)
    print("    stipple ink by scale: "
          + "  ".join("1:%d=%d" % (s, v) for s, v in sorted(extra.items())))
    lo, hi = min(extra.values()), max(extra.values())
    check(hi and (hi - lo) <= 0.15 * hi,
          "the stipple is the authored page size at 1:500, 1:5000 and "
          "1:20000 (%d..%d px) - this is what proves units=MM" % (lo, hi))

    for mineral, rgb in (("Chl", (86, 138, 94)), ("Hem", (176, 72, 58))):
        seed(lw, mm_line(40), dict(base, Selvedge_cm=30.0,
                                   SelvedgeMineral=mineral))
        got = near(render(lw, REF_SCALE, project),
                   composite(rgb, _inj.DOT_ALPHA))
        check(got > 100, "a %s selvedge draws %s dots (%d px)"
              % (mineral, rgb, got))

    seed(lw, mm_line(40), dict(base, Type="Vein Set / Sheeted"))
    off = ink(render(lw, REF_SCALE, project))
    seed(lw, mm_line(40), dict(base, Type="Vein Set / Sheeted",
                               Selvedge_cm=30.0))
    check(ink(render(lw, REF_SCALE, project)) == off,
          "Vein Set / Sheeted is untouched by a recorded selvedge")

    # A 1 mm pod has room for only a few dots per ring, so its bar is much
    # lower than the wide box's - the point of testing it is that it draws
    # SOMETHING rather than degenerating, which is where the inward band
    # this replaced used to flood the whole polygon.
    for name, wkt, floor in (("wide", mm_box(30, 20), 200),
                             ("1 mm pod", mm_box(1, 1), 10)):
        seed(bm, wkt, dict(Lithology1="VQ"))
        off = ink(render(bm, REF_SCALE, project))
        seed(bm, wkt, dict(Lithology1="VQ", Selvedge_cm=30.0,
                           SelvedgeMineral="Chl"))
        img = render(bm, REF_SCALE, project)
        got = near(img, composite((86, 138, 94), _inj.DOT_ALPHA))
        check(got > floor, "%s vein polygon grows a stipple (%d dot px, "
                           "floor %d)" % (name, got, floor))
        check(ink(img) > off,
              "%s: the stipple is EXTRA ink outside the polygon, not a "
              "recolour inside it" % name)

    for lyr in (lw, bm):
        project.removeMapLayer(lyr.id())


# ---------------------------------------------------------------------------
# 5. labels
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
    lw_expr = label_expr(style_of(GPKG, _inj.LW))
    bm_expr = label_expr(style_of(GPKG, _inj.BM))
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
    check("V2" not in got,
          "a non-vein lithology ignores stray vein data: %r" % got)

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
# 6. the label repeat
# ---------------------------------------------------------------------------

def test_label_repeat(tmp_gpkg):
    print("label repeat:")
    baked = _cartography.REPEAT_MU
    want = _setmapping.linework_repeat_for_scale(REF_SCALE)
    check(float(baked) == want,
          "the baked repeat (%s) is linework_repeat_for_scale(%d) = %s - the "
          "injector and Set Mapping Scale must not drift"
          % (baked, REF_SCALE, want))

    placement = style_of(GPKG, _inj.LW).find(".//labeling/settings/placement")
    check(placement.get("repeatDistance") == baked,
          "the template holds %s (got %s)"
          % (baked, placement.get("repeatDistance")))
    check(placement.get("repeatDistanceUnits") == "MapUnit",
          "the repeat is in MAP UNITS (got %s) - millimetres are "
          "paper-at-the-render-scale, which is the bug this fixes"
          % placement.get("repeatDistanceUnits"))

    project = QgsProject.instance()
    lyr = QgsVectorLayer("%s|layername=%s" % (tmp_gpkg, _inj.LW), "rep", "ogr")
    project.addMapLayer(lyr)
    lyr.setLabelsEnabled(True)
    seed(lyr, "LINESTRING(0 0, 12000 0)",
         dict(Category="Structural", Type="Fault", Label="F1"))

    def gaps(scale):
        gw = 1200 / DPI * 0.0254 * scale
        c = lyr.extent().center()
        ms = QgsMapSettings()
        ms.setOutputSize(QSize(1200, 300))
        ms.setOutputDpi(DPI)
        ms.setDestinationCrs(lyr.crs())
        ms.setExtent(QgsRectangle(c.x() - gw / 2, c.y() - gw * 0.12,
                                  c.x() + gw / 2, c.y() + gw * 0.12))
        ms.setLayers([lyr])
        ms.setBackgroundColor(QColor(255, 255, 255))
        job = QgsMapRendererParallelJob(ms)
        job.start()
        job.waitForFinished()
        res = job.takeLabelingResults()
        if not res:
            return []
        xs = sorted((l.labelRect.xMinimum() + l.labelRect.xMaximum()) / 2.0
                    for l in res.allLabels())
        # Adjacent rects can sit a few metres apart where PAL splits one
        # placement; only real repeats are of interest.
        return [b - a for a, b in zip(xs, xs[1:]) if b - a > 50]

    measured = {s: gaps(s) for s in (5000, 20000)}
    for scale, g in sorted(measured.items()):
        print("    1:%-6d ground gaps: %s"
              % (scale, [round(x) for x in g] or "-"))
    flat = sorted(x for g in measured.values() for x in g)
    check(flat, "the 12 km line repeats its label at all")
    if flat:
        median = flat[len(flat) // 2]
        # The typical gap is the repeat distance.  Gaps at the ends of the
        # visible line run short because PAL fits one last candidate before
        # the extent edge, so the median is the honest statistic.
        check(abs(median - want) <= 0.2 * want,
              "the typical repeat is ~%d ground metres, not %d (%s)"
              % (want, median, [round(x) for x in flat]))
        # The floor is what actually regressed: in millimetres this put a
        # label every 8 m of ground at 1:1000.
        check(flat[0] >= 0.35 * want,
              "no repeat is anywhere near as tight as the millimetre version "
              "was (shortest %d m, floor %d m)" % (flat[0], 0.35 * want))
    project.removeMapLayer(lyr.id())


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
        test_retired_codes()
        test_dd_expressions_parse()
        test_expressions()
        test_parse_budget()
        test_render(work)
        test_labels(work)
        test_label_repeat(work)
    finally:
        QgsProject.instance().removeAllMapLayers()
        qgs.exitQgis()
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
