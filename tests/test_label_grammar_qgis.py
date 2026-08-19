#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The label grammar, pinned as a table of rendered strings.

MUST run inside QGIS.

Map labels grew one value at a time, each addition appended with a space,
until a vein read `10cm Brt slv 10cm Afs` - two widths and two minerals with
nothing binding a value to the thing it measures.  The grammar is now:

    group        := [measurement] item[-item...]
    named group  := Name: group
    label        := group[, group...][?]
    item         := CODE[(value)]

This file is the table that grammar produces, one row per combination a
geologist can actually record.  It is deliberately a GOLDEN TABLE rather
than a set of rules: the failure mode here is not a crash, it is a label
that renders and reads badly, and the only way to catch that is to look at
what it says.  When a row changes, read the new string and decide whether it
is better - do not just update the expectation.

The invariants below the table are the ones that go wrong silently: a
doubled separator, a trailing comma, an empty group, or the trailing blank
lines that a raw concat used to leave on every Weathering polygon.

Usage:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests\\test_label_grammar_qgis.py
"""
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if os.path.join(REPO_ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import importlib  # noqa: E402

from qgis.core import (QgsApplication, QgsExpression,  # noqa: E402
                       QgsExpressionContext, QgsExpressionContextScope,
                       QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer)

_grammar = importlib.import_module("inject_label_grammar")

GPKG = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
LINE = "LINESTRING(0 0, 10 0)"
POLY = "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"

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


def label_expr(layer):
    con = sqlite3.connect("file:%s?mode=ro" % GPKG.replace("\\", "/"), uri=True)
    try:
        qml = con.execute("SELECT styleQML FROM layer_styles "
                          "WHERE f_table_name=?", (layer,)).fetchone()[0]
    finally:
        con.close()
    return ET.fromstring(qml).find(
        ".//labeling/settings/text-style").get("fieldName")


def render(expr, lyr, wkt, attrs):
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
    if e.hasParserError():
        return "<PARSE ERROR: %s>" % e.parserErrorString()
    e.prepare(ctx)
    out = e.evaluate(ctx)
    if e.hasEvalError():
        return "<EVAL ERROR: %s>" % e.evalErrorString()
    return "" if out is None else str(out)


def plain(html):
    """Basemap renders HTML; ' | ' marks where one <div> line ends."""
    s = re.sub(r"</div>\s*<div[^>]*>", " | ", html)
    s = re.sub(r"</?span[^>]*>|</?div[^>]*>", "", s)
    return s.strip()


# --- the table -------------------------------------------------------------
# (name, attributes, expected rendered label)

VEIN = dict(Category="Veins", Type="Vein - Quartz")

LINEWORK = [
    ("nothing recorded",       dict(VEIN), ""),
    ("width only",             dict(VEIN, Width_cm=10.0), "10cm"),
    ("width + mineral",        dict(VEIN, Width_cm=10.0, Mineral1="Brt"),
                               "10cm Brt"),
    ("width + mineral%",       dict(VEIN, Width_cm=10.0, Mineral1="Qz",
                                    Mineral1Pct=10), "10cm Qz(10%)"),
    ("mineral% of zero",       dict(VEIN, Width_cm=10.0, Mineral1="Qz",
                                    Mineral1Pct=0), "10cm Qz"),
    ("three minerals",         dict(VEIN, Width_cm=10.0, Mineral1="Qz",
                                    Mineral1Pct=60, Mineral2="Py",
                                    Mineral2Pct=5, Mineral3="Ser"),
                               "10cm Qz(60%)-Py(5%)-Ser"),
    ("generation",             dict(VEIN, VeinGen="V2", Width_cm=10.0,
                                    Mineral1="Brt"), "V2 10cm Brt"),
    # The row this whole grammar exists for.
    ("vein + selvedge",        dict(VEIN, Width_cm=10.0, Mineral1="Brt",
                                    Selvedge_cm=10.0, SelvedgeMineral="Afs"),
                               "10cm Brt, Slv: 10cm Afs"),
    ("selvedge, no widths",    dict(VEIN, Mineral1="Brt",
                                    SelvedgeMineral="Afs"), "Brt, Slv: Afs"),
    ("selvedge width only",    dict(VEIN, Width_cm=10.0, Selvedge_cm=3.0),
                               "10cm, Slv: 3cm"),
    ("everything",             dict(VEIN, VeinGen="V2", Width_cm=10.0,
                                    Mineral1="Qz", Mineral1Pct=60,
                                    Mineral2="Py", Mineral2Pct=5,
                                    Selvedge_cm=10.0, SelvedgeMineral="Afs",
                                    Label="lens", Confidence="Queried"),
                               "V2 10cm Qz(60%)-Py(5%), Slv: 10cm Afs, lens?"),
    ("mm and m widths",        dict(VEIN, Width_cm=0.5, Selvedge_cm=120.0),
                               "5mm, Slv: 1.2m"),
    ("dyke",                   dict(Category="Lithology", Type="Dyke",
                                    Width_cm=120.0, Mineral1="Qz"), "1.2m Qz"),
    ("fault, width + name",    dict(Category="Structural", Type="Fault",
                                    Width_cm=200.0, Label="F1"), "2m, F1"),
    ("fault, queried",         dict(Category="Structural", Type="Fault",
                                    Label="F1", Confidence="Queried"), "F1?"),
    # A stray vein value on a non-vein must not print - the symbology draws
    # no selvedge there, and a label must not promise ink that cannot appear.
    ("fault, stray vein data", dict(Category="Structural", Type="Fault",
                                    Label="F1", VeinGen="V2",
                                    Selvedge_cm=9.0), "F1"),
    ("formline (out of scope)", dict(Category="Formlines",
                                     Type="Formline - S1", Label="S1"), "S1"),
]

BASEMAP = [
    ("lith only",              dict(Lithology1="VN"), "VN"),
    ("lith + mineral",         dict(Lithology1="FGR", Lith1Mineral1="Qtz"),
                               "FGR (Qtz)"),
    ("lith + mineral%",        dict(Lithology1="FGR", Lith1Mineral1="Qtz",
                                    Lith1Mineral1Pct=5), "FGR (Qtz(5%))"),
    # Linework has always hidden a zero; Basemap used to print 'Qtz(0%)'.
    ("mineral% of zero",       dict(Lithology1="FGR", Lith1Mineral1="Qtz",
                                    Lith1Mineral1Pct=0), "FGR (Qtz)"),
    ("minerals + textures",    dict(Lithology1="FGR", Lith1Mineral1="Qtz",
                                    Lith1Mineral1Pct=5, Lith1Mineral2="Fsp",
                                    Lith1Mineral3="Gn", Lith1Mineral3Pct=5,
                                    Lith1Texture1="Bnd", Lith1Texture2="Fol"),
                               "FGR (Qtz(5%)-Fsp-Gn(5%), Bnd-Fol)"),
    ("prefix + sulphides",     dict(Lithology1="FGR", LithologyPrefix="H",
                                    **{"Sulphides/Mineralisation": "*"}),
                               "* H-FGR"),
    ("vein + selvedge",        dict(Lithology1="VN", Selvedge_cm=100.0,
                                    SelvedgeMineral="Py"), "VN, Slv: 1m Py"),
    ("vein + gen + selvedge",  dict(Lithology1="VN", VeinGen="V3",
                                    Selvedge_cm=100.0, SelvedgeMineral="Py"),
                               "VN, V3, Slv: 1m Py"),
    # The vein tag must land AFTER the unit's own modifiers, not between the
    # code and them.
    ("vein, modifiers + slv",  dict(Lithology1="VQ", Lith1Mineral1="Qtz",
                                    Lith1Mineral1Pct=90, Lith1Texture1="Bnd",
                                    VeinGen="V2", Selvedge_cm=5.0,
                                    SelvedgeMineral="Ser"),
                               "VQ (Qtz(90%), Bnd), V2, Slv: 5cm Ser"),
    ("two lithologies",        dict(Lithology1="VQ", Lithology2="FGR",
                                    Lith2Mineral1="Bt"), "VQ | FGR (Bt)"),
    ("queried",                dict(Lithology1="VQ", Confidence="Queried"),
                               "VQ?"),
    ("non-vein ignores slv",   dict(Lithology1="FGR", VeinGen="V2",
                                    Selvedge_cm=3.0), "FGR"),
    ("uncoded free text",      dict(UncodedLithology="odd grey rock"),
                               "odd grey rock"),
]

OVERLAY = [
    ("alteration",             dict(Type="Alteration", SubType1="Ser",
                                    Intensity=3), "Ser (3)"),
    ("alteration, 3 subtypes", dict(Type="Alteration", SubType1="Ser",
                                    SubType2="Chl", SubType3="Py",
                                    Intensity=5), "Ser-Chl-Py (5)"),
    ("structure",              dict(Type="Structure", SubType1="Shear Zone",
                                    Weight="Major"), "Shear Zone (Major)"),
    # SubType2/3 are offered on the form for every Type; this branch used to
    # read SubType1 and silently drop the rest.
    ("structure + subtype2",   dict(Type="Structure", SubType1="Shear Zone",
                                    SubType2="Damage Zone", Weight="Major"),
                               "Shear Zone-Damage Zone (Major)"),
    ("mineralisation",         dict(Type="Mineralisation",
                                    SubType1="Stringer Zone", Mineral1="Gn",
                                    Percent=12), "Stringer Zone, Gn(12%)"),
    ("mineralisation, no pct", dict(Type="Mineralisation",
                                    SubType1="Barren Zone"), "Barren Zone"),
    ("mineralisation, pct 0",  dict(Type="Mineralisation",
                                    SubType1="Vein Zone", Mineral1="Py",
                                    Percent=0), "Vein Zone, Py"),
    # These two used to fall through a raw three-way concat and emit the
    # subtype followed by two blank lines.
    ("weathering",             dict(Type="Weathering", SubType1="Oxidised"),
                               "Oxidised"),
    ("weathering, 2 subtypes", dict(Type="Weathering", SubType1="Fresh",
                                    SubType2="Saprock"), "Fresh-Saprock"),
    ("infrastructure",         dict(Type="Infrastructure",
                                    SubType1="Pit Outline"), "Pit Outline"),
    ("queried",                dict(Type="Structure", SubType1="Fault Zone",
                                    Weight="Minor", Confidence="Queried"),
                               "Fault Zone (Minor)?"),
]


def run_table(name, lyr, expr, wkt, table, normalise=lambda s: s):
    print("%s:" % name)
    got_all = []
    for case, attrs, want in table:
        got = normalise(render(expr, lyr, wkt, attrs))
        got_all.append((case, got))
        check(got == want, "%-24s %r  !=  %r" % (case, got, want))
    return got_all


def check_invariants(name, rows):
    """The ways a joined label goes wrong without anyone noticing."""
    for case, got in rows:
        where = "%s / %s" % (name, case)
        check("  " not in got, where + ": doubled space in %r" % got)
        check(", ," not in got and ",," not in got,
              where + ": empty group in %r" % got)
        check(not got.endswith(",") and not got.endswith(", "),
              where + ": trailing separator in %r" % got)
        check(got == got.strip(), where + ": padded with space in %r" % got)
        check("\n" not in got, where + ": stray newline in %r" % got)
        check("--" not in got, where + ": empty item in the chain, %r" % got)


def test_markup(tmp):
    """The Basemap HTML contract inject_label_cartography counts on."""
    print("basemap markup:")
    expr = label_expr("4 - Basemap")
    cart = importlib.import_module("inject_label_cartography")
    check(expr.count(cart.DIV_BOLD) == cart.N_DIV,
          "exactly %d semibold divs (%d)" % (cart.N_DIV,
                                             expr.count(cart.DIV_BOLD)))
    check(cart.DIV not in expr.replace(cart.DIV_BOLD, ""),
          "no plain <div> survived")
    check(cart.SPAN not in expr.replace(cart.SPAN_LIGHT, ""),
          "no plain span survived - a later injector must use the "
          "font-weight:400 variant or weight_split() miscounts")
    check(expr.count(cart.SPAN_LIGHT) >= cart.N_SPAN,
          "at least %d light spans" % cart.N_SPAN)


def test_owners_agree():
    """The constants other injectors splice against still match the template."""
    print("owners agree:")
    ovl = importlib.import_module("inject_overlay_mineralisation")
    lw_min = importlib.import_module("inject_linework_mineral_pcts")
    slv = importlib.import_module("inject_vein_generation_selvedge")
    conf = importlib.import_module("inject_confidence_system")
    lw = label_expr("2 - Linework")
    ov = label_expr("3 - Overlay")
    bm = label_expr("4 - Basemap")

    check(lw == _grammar.LW_LABEL,
          "inject_label_grammar owns the Linework label verbatim")
    for n in (1, 2, 3):
        check(lw.count(lw_min.mineral_piece(n)) == 1,
              "mineral token %d appears exactly once" % n)
    check(slv.LW_GEN_TEXT in lw and slv.LW_SLV_TEXT in lw,
          "the generation and selvedge fragments survive in the Linework label")
    check(slv.BM_TAG in bm, "the vein tag survives in the Basemap label")
    for layer, expr in (("Linework", lw), ("Overlay", ov)):
        check(expr.rstrip().endswith(conf.QUERIED_SUFFIX),
              "%s: the Confidence suffix is the last term, or a re-run of "
              "inject_confidence_system appends a second '?'" % layer)
    check(ovl.NEW_LABEL_BRANCH in ov,
          "inject_overlay_mineralisation.NEW_LABEL_BRANCH still matches")
    check(ovl.OLD_LABEL_TAIL in ov,
          "inject_overlay_mineralisation.OLD_LABEL_TAIL - its splice anchor - "
          "still matches")
    check("'Alteration'" in ov,
          "inject_overlay_label_placement.py asserts this literal survives")
    check("concat(" not in ov,
          "the raw concat is gone, so no more trailing blank lines")


def main():
    if not os.path.exists(GPKG):
        print("template not found: %s" % GPKG)
        return 2
    qgs = QgsApplication([], False)
    qgs.initQgis()
    tmp = tempfile.mkdtemp(prefix="lgs-labels-")
    try:
        work = os.path.join(tmp, "t.gpkg").replace("\\", "/")
        shutil.copy2(GPKG, work)
        lw = QgsVectorLayer("%s|layername=2 - Linework" % work, "lw", "ogr")
        ov = QgsVectorLayer("%s|layername=3 - Overlay" % work, "ov", "ogr")
        bm = QgsVectorLayer("%s|layername=4 - Basemap" % work, "bm", "ogr")
        if not check(lw.isValid() and ov.isValid() and bm.isValid(),
                     "all three layers open"):
            return 1
        rows = run_table("2 - Linework", lw, label_expr("2 - Linework"),
                         LINE, LINEWORK)
        check_invariants("Linework", rows)
        rows = run_table("4 - Basemap", bm, label_expr("4 - Basemap"),
                         POLY, BASEMAP, normalise=plain)
        check_invariants("Basemap", rows)
        rows = run_table("3 - Overlay", ov, label_expr("3 - Overlay"),
                         POLY, OVERLAY)
        check_invariants("Overlay", rows)
        test_markup(work)
        test_owners_agree()
    finally:
        # Drop every layer reference BEFORE exitQgis, and flush what has
        # been printed: a QgsVectorLayer still alive at teardown segfaults,
        # and a segfault loses the whole buffered report - which shows up
        # as a test that printed nothing and 'passed'.
        lw = ov = bm = None
        QgsProject.instance().removeAllMapLayers()
        sys.stdout.flush()
        qgs.exitQgis()
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
