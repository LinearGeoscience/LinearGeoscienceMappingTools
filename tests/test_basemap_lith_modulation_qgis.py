#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify the per-feature Basemap modulation (MUST run inside QGIS).

Covers the things that could silently rot:

  1. The live template carries the two virtual fields and all 301 dd
     fillColor expressions (300 categories + source-symbol), and every
     expression parses.
  2. BYTE-IDENTITY: a feature with no modifiers renders pixel-identically
     to the same symbol with the dd stripped. This is the @symbol_color
     fast path - the whole design rests on unmodified features being
     untouched, and on @symbol_color resolving inside a dd fill override.
  3. Modifiers actually modulate: Lithology2 shifts the fill (visibly, but
     by less than a code-separation), a whitelisted texture nudges it, a
     non-whitelisted one does not.
  4. The patterns template still carries exactly ONE SVGFill - now with
     file/outlineColor/outlineWidth/width dd - and the width and stroke
     expressions evaluate to the exact TSV multipliers (NULL modifiers ->
     exactly TILE_WIDTH_PT and the base ink).
  5. The mineral ink tint evaluates to exactly
     color_mix_rgb(base_ink, family_ink, MINERAL_MIX) - or the base ink
     where the code is excluded for legibility - never anything else.
  6. renderer_compat still reads both templates and never treats the
     pattern rule as a class.

Run:  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests/test_basemap_lith_modulation_qgis.py
"""

import os
import re
import sqlite3
import sys
import time

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
PARENT = os.path.dirname(REPO_ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
if os.path.join(REPO_ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
PKG = os.path.basename(REPO_ROOT)

import importlib  # noqa: E402

from qgis.core import (QgsApplication, QgsVectorLayer, QgsFeature,  # noqa: E402
                       QgsGeometry, QgsMapSettings, QgsRectangle,
                       QgsCoordinateReferenceSystem, QgsFields,
                       QgsMapRendererCustomPainterJob, QgsExpression,
                       QgsExpressionContext, QgsExpressionContextUtils,
                       QgsCategorizedSymbolRenderer, QgsRuleBasedRenderer,
                       QgsSymbolLayer, QgsProperty)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QImage, QPainter, QColor  # noqa: E402

renderer_compat = importlib.import_module(PKG + ".renderer_compat")
_inj = importlib.import_module("inject_basemap_lith_patterns")
_mod = importlib.import_module("inject_basemap_lith_modulation")

ORIGINAL = _inj.ORIGINAL
TARGET = _inj.TARGET
LAYER = _inj.LAYER

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


FIELDS = ["Lithology1", "Lithology2", "ContactType",
          "Lith1Texture1", "Lith1Texture2", "Lith1Mineral1"]


def make_mem(template_layer, attrs):
    """One-feature memory layer wearing the template's renderer AND its
    virtual fields (a bare memory layer lacks them, and the dd expressions
    reference them)."""
    mem = QgsVectorLayer(
        "Polygon?crs=EPSG:3857&" +
        "&".join("field=%s:string" % f for f in FIELDS), "t", "memory")
    f = QgsFeature(mem.fields())
    f.setAttribute("ContactType", "None")
    for k, v in attrs.items():
        f.setAttribute(k, v)
    f.setGeometry(QgsGeometry.fromWkt(
        "POLYGON((0 0,40 0,40 26,0 26,0 0))"))
    mem.dataProvider().addFeatures([f])
    mem.updateExtents()
    fields = template_layer.fields()
    for i in range(fields.count()):
        if fields.fieldOrigin(i) == QgsFields.OriginExpression:
            mem.addExpressionField(template_layer.expressionField(i),
                                   fields.at(i))
    mem.setRenderer(template_layer.renderer().clone())
    return mem


def render_one(mem, w=200, h=130):
    ms = QgsMapSettings()
    ms.setLayers([mem])
    ms.setExtent(QgsRectangle(0, 0, 40, 26))
    ms.setOutputSize(QSize(w, h))
    ms.setBackgroundColor(QColor(255, 255, 255))
    ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    im = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    im.fill(QColor(255, 255, 255))
    p = QPainter(im)
    job = QgsMapRendererCustomPainterJob(ms, p)
    job.start()
    job.waitForFinished()
    p.end()
    return im


def centre_rgb(im):
    c = im.pixelColor(im.width() // 2, im.height() // 2)
    return (c.red(), c.green(), c.blue())


def images_equal(a, b):
    return a == b


def eval_expr(expr_text, attrs, fields_layer):
    """Evaluate an expression against a one-feature context carrying attrs."""
    mem = QgsVectorLayer(
        "Polygon?crs=EPSG:3857&" +
        "&".join("field=%s:string" % f for f in FIELDS), "e", "memory")
    f = QgsFeature(mem.fields())
    for k, v in attrs.items():
        f.setAttribute(k, v)
    exp = QgsExpression(expr_text)
    ctx = QgsExpressionContext()
    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(mem))
    ctx.setFeature(f)
    exp.prepare(ctx)
    val = exp.evaluate(ctx)
    err = exp.hasEvalError() or exp.hasParserError()
    del mem
    return val, err


def main():
    global _passed, _failed
    QgsApplication.setPrefixPath(os.environ.get(
        "QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        run(app)
    finally:
        app.exitQgis()
        del app
    print("\n%d passed, %d failed" % (_passed, _failed))
    sys.exit(1 if _failed else 0)


def run(app):
    # ---- 1. live template QML shape ----------------------------------
    con = sqlite3.connect("file:%s?mode=ro" % ORIGINAL.replace("\\", "/"),
                          uri=True)
    live_qml = con.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()[0]
    con.close()
    for name in _mod.ALL_FIELDS:
        check(('<field name="%s"' % name) in live_qml,
              "virtual field %s in live template" % name)
    blocks = _mod.FILLCOLOR_BLOCK.findall(live_qml)
    ours = [b for b in blocks
            if _mod.MODFILL_FIELD in b and "symbol_color" in b]
    check(len(ours) == _mod.EXPECT_SLOTS,
          "%d dd fillColor modulation expressions (found %d)"
          % (_mod.EXPECT_SLOTS, len(ours)))

    # every distinct symbol expression parses, and so do the virtual fields
    vf = dict(re.findall(
        r'<field name="(LGS_\w+)"[^>]*expression="([^"]*)"', live_qml))
    import xml.sax.saxutils as sx
    for name, raw in vf.items():
        expr = sx.unescape(raw, {"&quot;": '"', "&#13;": "\r", "&#10;": "\n"})
        check(not QgsExpression(expr).hasParserError(),
              "%s expression parses" % name)
    distinct_exprs = set()
    for b in ours:
        m = re.search(r'name="expression" type="QString" value="([^"]*)"', b)
        if m:
            distinct_exprs.add(sx.unescape(
                m.group(1), {"&quot;": '"', "&#13;": "\r", "&#10;": "\n"}))
    check(distinct_exprs == {_mod.SYMBOL_EXPR},
          "all 301 symbol expressions are the ONE tiny coalesce "
          "(found %d distinct)" % len(distinct_exprs))
    check(all(not QgsExpression(e).hasParserError() for e in distinct_exprs),
          "the symbol expression parses")

    # ---- 2. byte-identity for unmodified features --------------------
    live = QgsVectorLayer("%s|layername=%s" % (ORIGINAL, LAYER), LAYER, "ogr")
    check(live.isValid(), "live template layer opens")
    check(isinstance(live.renderer(), QgsCategorizedSymbolRenderer),
          "live renderer is categorized")

    mem_plain = make_mem(live, {"Lithology1": "SST"})
    im_dd = render_one(mem_plain)

    mem_strip = make_mem(live, {"Lithology1": "SST"})
    stripped = 0
    for cat in mem_strip.renderer().categories():
        sl = cat.symbol().symbolLayer(0)
        prop = sl.dataDefinedProperties().property(
            QgsSymbolLayer.PropertyFillColor)
        if prop and prop.isActive():
            sl.setDataDefinedProperty(QgsSymbolLayer.PropertyFillColor,
                                      QgsProperty())
            stripped += 1
    check(stripped == 300, "stripped dd from all 300 category symbols "
          "(got %d)" % stripped)
    im_plain = render_one(mem_strip)
    check(images_equal(im_dd, im_plain),
          "no-modifier feature renders BYTE-IDENTICALLY with dd active")

    # ---- 3. modifiers modulate ---------------------------------------
    base_rgb = centre_rgb(im_dd)
    im_l2 = render_one(make_mem(live, {"Lithology1": "SST",
                                       "Lithology2": "UKO"}))
    l2_rgb = centre_rgb(im_l2)
    de = _inj.delta_e(base_rgb, l2_rgb)
    check(de > _inj.IDENTICAL_DE,
          "Lithology2 shifts the fill visibly (dE %.2f)" % de)
    check(de < _inj.MIN_FILL_DE,
          "Lithology2 shift stays below a code separation (dE %.2f)" % de)

    im_fol = render_one(make_mem(live, {"Lithology1": "SST",
                                        "Lith1Texture1": "Foliated"}))
    check(centre_rgb(im_fol) != base_rgb,
          "whitelisted texture (Foliated) nudges the fill")
    im_mas = render_one(make_mem(live, {"Lithology1": "SST",
                                        "Lith1Texture1": "Massive"}))
    check(images_equal(im_mas, im_plain),
          "non-whitelisted texture (Massive) changes nothing")

    # a feature of a capped code still blends, just less
    im_cap = render_one(make_mem(live, {"Lithology1": "SSTM",
                                        "Lithology2": "UKO"}))
    im_cap_base = render_one(make_mem(live, {"Lithology1": "SSTM"}))
    check(centre_rgb(im_cap) != centre_rgb(im_cap_base),
          "capped code still blends")

    # ---- 4. patterns template shape + width/stroke expressions -------
    con = sqlite3.connect("file:%s?mode=ro" % TARGET.replace("\\", "/"),
                          uri=True)
    pat_qml = con.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()[0]
    con.close()
    check(len(re.findall(r'class="SVGFill"', pat_qml)) == 1,
          "patterns template still carries exactly ONE SVGFill")
    for name in _mod.ALL_FIELDS:
        check(re.search(r'<field\b[^>]*name="%s"' % name, pat_qml)
              is not None,
              "virtual field %s survives the bake" % name)
    n_rules = len(re.findall(r'<rule\b', pat_qml))
    check(n_rules == 301, "301 rules in the bake (found %d)" % n_rules)

    pat = QgsVectorLayer("%s|layername=%s" % (TARGET, LAYER), LAYER, "ogr")
    check(pat.isValid(), "patterns template layer opens")
    check(isinstance(pat.renderer(), QgsRuleBasedRenderer),
          "patterns renderer is rule-based")
    svg_layer = None
    for rule in pat.renderer().rootRule().children():
        if rule.label() == renderer_compat.PATTERN_RULE_LABEL:
            svg_layer = rule.symbol().symbolLayer(0)
    check(svg_layer is not None, "pattern rule found by label")

    props = svg_layer.dataDefinedProperties()
    width_prop = props.property(QgsSymbolLayer.PropertyWidth)
    check(width_prop is not None and width_prop.isActive(),
          "dd width on the SVGFill")
    width_expr = width_prop.asExpression()
    col_expr = props.property(
        QgsSymbolLayer.PropertyStrokeColor).asExpression()
    wid_expr = props.property(
        QgsSymbolLayer.PropertyStrokeWidth).asExpression()

    mod_tsv = _inj.load_texture_modulation()
    for tex, mult in (("Pegmatitic", 1.38), ("Very Fine Grained", 0.78)):
        check(abs(mod_tsv["tile"][tex] - mult) < 1e-9,
              "texture_modulation.tsv holds %s at %.2f" % (tex, mult))
        val, err = eval_expr(width_expr,
                             {"Lithology1": "SST", "Lith1Texture1": tex}, pat)
        check(not err and abs(float(val) - _inj.TILE_WIDTH_PT * mult) < 1e-6,
              "width expr: %s -> %.2f pt (got %r)"
              % (tex, _inj.TILE_WIDTH_PT * mult, val))
        # texture in the SECOND slot must work too
        val2, err2 = eval_expr(width_expr,
                               {"Lithology1": "SST", "Lith1Texture2": tex},
                               pat)
        check(not err2 and abs(float(val2) - _inj.TILE_WIDTH_PT * mult) < 1e-6,
              "width expr honours Lith1Texture2 (%s)" % tex)
    val, err = eval_expr(width_expr, {"Lithology1": "SST"}, pat)
    check(not err and abs(float(val) - _inj.TILE_WIDTH_PT) < 1e-9,
          "width expr: no grain size -> exactly %.1f pt" % _inj.TILE_WIDTH_PT)

    val, err = eval_expr(wid_expr, {"Lithology1": "SST"}, pat)
    base_stroke = float(val)
    check(not err and base_stroke > 0, "stroke expr evaluates for SST")
    val, err = eval_expr(wid_expr, {"Lithology1": "SST",
                                    "Lith1Texture1": "Pegmatitic"}, pat)
    check(not err and abs(float(val) - base_stroke * (1.38 ** 0.5)) < 1e-3,
          "stroke compensated by sqrt(multiplier) for Pegmatitic")

    # ---- 5. mineral ink tint evaluates to the exact blend ------------
    inks = _inj.load_mineral_inks()
    families = _inj.load_mineral_families(inks)
    check(families.get("Qz") == "quartz" and families.get("Hem") == "iron_oxide",
          "mineral_families.tsv maps Qz->quartz, Hem->iron_oxide")

    def to_rgb(v):
        """(r,g,b) out of whatever the expression engine hands back:
        a QColor, an 'r,g,b[,a]' string, or a '#rrggbb' hex."""
        if hasattr(v, "red"):
            return (v.red(), v.green(), v.blue())
        s = str(v)
        if "," in s:
            parts = s.split(",")
            return tuple(int(round(float(p))) for p in parts[:3])
        s = s.lstrip("#")
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))

    n_tinted = 0
    for code, mineral in (("SST", "Qz"), ("MG", "Hem"), ("SSL", "Cal"),
                          ("FGR", "Bt")):
        v0, e0 = eval_expr(col_expr, {"Lithology1": code}, pat)
        v1, e1 = eval_expr(col_expr, {"Lithology1": code,
                                      "Lith1Mineral1": mineral}, pat)
        if check(not (e0 or e1), "ink expr evaluates for %s/%s"
                 % (code, mineral)):
            base = to_rgb(v0)
            got = to_rgb(v1)
            fam_rgb = inks[families[mineral]]
            expect = _inj.mix_rgb(base, fam_rgb, _inj.MINERAL_MIX)
            # allow 1/channel for the engine's own rounding
            if all(abs(g - e) <= 1 for g, e in zip(got, expect)):
                n_tinted += 1
                ok = True
            else:
                # excluded for legibility: base ink must come back verbatim
                ok = got == base
            check(ok, "%s + %s ink is the exact blend or the base ink "
                  "(got %s, base %s, blend %s)" % (code, mineral, got,
                                                   base, expect))
    check(n_tinted >= 2,
          "at least two probe pairs actually tint (got %d)" % n_tinted)
    val, err = eval_expr(col_expr, {"Lithology1": "SST"}, pat)
    v2, e2 = eval_expr(col_expr, {"Lithology1": "SST",
                                  "Lith1Mineral1": "Zrn"}, pat)
    check(not (err or e2) and to_rgb(val) == to_rgb(v2),
          "unmapped mineral (Zrn) leaves the ink alone")

    # ---- 6. renderer_compat + timing ---------------------------------
    for layer, label in ((live, "live"), (pat, "patterns")):
        classes = renderer_compat.renderer_classes(layer.renderer())
        check(len(classes) == 300,
              "%s: 300 classes via renderer_compat" % label)
        check(renderer_compat.PATTERN_RULE_LABEL
              not in [v for v, _s in classes],
              "%s: pattern rule is not a class" % label)

    mem = make_mem(pat, {"Lithology1": "SST", "Lithology2": "UKO",
                         "Lith1Texture1": "Coarse Grained",
                         "Lith1Mineral1": "Qz"})
    t0 = time.perf_counter()
    for _ in range(5):
        render_one(mem)
    dt = (time.perf_counter() - t0) / 5 * 1000
    print("  timing: full modulated redraw %.1f ms/frame (informational; "
          "pre-modulation baseline was ~6.1 ms renderer cost)" % dt)


if __name__ == "__main__":
    main()
