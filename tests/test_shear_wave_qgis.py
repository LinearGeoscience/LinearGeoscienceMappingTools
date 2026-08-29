"""The Shear Zone Boundary stroke actually waves, and nothing else moved.

A GeometryGenerator fails silently: a typo in its expression renders as
nothing, with no error anywhere.  So beyond checking the structure that
inject_linework_shear_wave.py wrote, this test parses every expression,
evaluates the wave off-line, and renders the symbol to pixels to prove
four separate claims:

  1. the stroke undulates (red ink spreads wider than a straight 1.46 pt
     line could);
  2. the inward-arrow MarkerLine survived (ink beyond the bare stroke);
  3. Confidence='Inferred' still dashes the wavy path (the preserved
     customDash dd works through the generator);
  4. Weight='Major' still thickens it (the preserved outlineWidth dd).

Run under the QGIS python:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests\\test_shear_wave_qgis.py
"""

import os
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

_inj = importlib.import_module("inject_linework_shear_wave")

GPKG = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
REF_SCALE = 5000
PX_W, PX_H, DPI = 460, 300, 96.0

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
    con = sqlite3.connect("file:%s?mode=ro" % gpkg.replace("\\", "/"),
                          uri=True)
    try:
        row = con.execute("SELECT styleQML FROM layer_styles "
                          "WHERE f_table_name=?", (layer,)).fetchone()
    finally:
        con.close()
    return ET.fromstring(row[0])


def find_symbol(root):
    """The renderer symbol behind the Shear Zone Boundary category."""
    renderer = root.find("renderer-v2")
    name = None
    for cat in renderer.iter("category"):
        if cat.get("value") == _inj.CODE:
            name = cat.get("symbol")
    if name is None:
        return None, None
    for sym in renderer.find("symbols").findall("symbol"):
        if sym.get("name") == name:
            return name, sym
    return name, None


# ---------------------------------------------------------------------------
# 1. structure
# ---------------------------------------------------------------------------

def test_structure():
    print("structure:")
    root = style_of(GPKG, _inj.LW)
    check(root.get("simplifyDrawingHints") == "0",
          "render simplification off - it would drift the crests with zoom")
    name, sym = find_symbol(root)
    if not check(sym is not None, "category + symbol found"):
        return
    layers = sym.findall("layer")
    if not check(len(layers) == 2,
                 "two layers: generator under arrows (got %d)" % len(layers)):
        return
    gen, marker = layers

    opts = {o.get("name"): o.get("value")
            for o in gen.find("Option").findall("Option")}
    check(gen.get("class") == "GeometryGenerator", "layer 0 is the generator")
    check(gen.get("id") == _inj.GEN_ID, "generator carries the stable id")
    check(opts.get("SymbolType") == "Line", "SymbolType Line")
    check(opts.get("units") == "MapUnit",
          "units MapUnit - a mm modifier would re-flow on every zoom")
    check(opts.get("geometryModifier") == _inj.WAVE_EXPR,
          "modifier is the injector's WAVE_EXPR")
    check("@lgs_reference_scale" in opts.get("geometryModifier", ""),
          "the wave size follows the mapping scale variable")
    check(sym.get("clip_to_extent") == "0",
          "unclipped: clipped input would re-phase the tildes on pan")

    check(marker.get("class") == "MarkerLine", "arrows still on top")
    mopts = {o.get("name"): o.get("value")
             for o in marker.find("Option").findall("Option")}
    check(mopts.get("interval") == "14", "arrow interval untouched")
    # The 2.0 mm standoff moved INTO the stem_arrow.svg canvas on 30 Aug
    # 2026 (inject_linework_marker_decorations) so it scales with Weight.
    check(mopts.get("offset") == "0", "arrow MarkerLine offset baked to 0")
    check(mopts.get("rotate") == "1", "arrows still rotate with the line")
    svg = [l for l in marker.iter("layer") if l.get("class") == "SvgMarker"]
    check(len(svg) == 1, "the inward-arrow SvgMarker survived")
    if svg:
        sopts = {o.get("name"): o.get("value")
                 for o in svg[0].find("Option").findall("Option")}
        check(sopts.get("size") == "2.4", "arrow size untouched")

    stroke = gen.find("symbol").find("layer")
    check(stroke is not None and stroke.get("class") == "SimpleLine",
          "the stroke lives inside the generator")
    if stroke is None:
        return
    st = {o.get("name"): o.get("value")
          for o in stroke.find("Option").findall("Option")}
    check(st.get("line_width") == "1.46", "stroke width untouched")
    check(st.get("line_color", "").startswith("255,29,29"),
          "stroke colour untouched")
    check(st.get("line_style") == "solid" and st.get("use_custom_dash") == "0",
          "base stroke stays solid (confidence flips it per-feature)")
    dd = ET.tostring(stroke.find("data_defined_properties"),
                     encoding="unicode")
    check("customDash" in dd and "100000;1" in dd,
          "customDash dd pinned to the neutral mega-dash")
    check("Inferred" not in dd,
          "no live confidence dash left to cut the tildes a second time")
    check("Inferred" in opts.get("geometryModifier", ""),
          "the generator owns the Inferred rendering")
    check("outlineWidth" in dd and "Weight" in dd,
          "Weight outlineWidth dd preserved on the nested stroke")
    for el in (sym, gen, marker, gen.find("symbol"), stroke):
        check(el.find("data_defined_properties") is not None,
              "every layer owns a dd block (weight-scaling guard)")


# ---------------------------------------------------------------------------
# 2. expressions parse (a generator fails silently - this is the point)
# ---------------------------------------------------------------------------

def test_expressions_parse():
    print("expressions parse:")
    check(not QgsExpression(_inj.WAVE_EXPR).hasParserError(),
          "WAVE_EXPR parses")
    root = style_of(GPKG, _inj.LW)
    _, sym = find_symbol(root)
    n = 0
    for entry in sym.iter("Option"):
        if entry.get("name") not in ("customDash", "outlineWidth",
                                     "geometryModifier"):
            continue
        expr = entry.get("value")
        if expr is None:      # the dd Map container, not the value option
            for o in entry.findall("Option"):
                if o.get("name") == "expression":
                    expr = o.get("value")
        if expr is None:
            continue
        n += 1
        check(not QgsExpression(expr).hasParserError(),
              "%s expression parses" % entry.get("name"))
    check(n >= 3, "found the modifier + both dd expressions (%d)" % n)


# ---------------------------------------------------------------------------
# 3. the wave evaluates
# ---------------------------------------------------------------------------

def evaluate(expr, wkt, conf=None, scale=REF_SCALE):
    """Drive the "Confidence" field through a same-named variable - fields
    are unavailable without a layer (the selvedge as_vars trick) - and
    publish the mapping-scale variable the ground-locked wave reads."""
    expr = expr.replace('"Confidence"', "@Confidence")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt(wkt))
    ctx = QgsExpressionContext()
    scope = QgsExpressionContextScope()
    scope.setVariable("Confidence", conf)
    scope.setVariable("lgs_reference_scale", scale)
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


def test_wave_evaluates():
    print("wave evaluates:")
    # Ground space now: at 1:5000 a 10 mm tilde is 50 m and the 5 mm gap
    # is 25 m, so the step is 75 m.  A 235 m line fits three whole tildes.
    TILDE = _inj.TILDE_MM / 1000.0 * REF_SCALE          # 50 m
    STEP = (_inj.TILDE_MM + _inj.GAP_MM) / 1000.0 * REF_SCALE   # 75 m
    straight = "LINESTRING(0 0, 235 0)"
    curved = "LINESTRING(0 0, 75 30, 150 -20, 235 0)"
    crossing = "LINESTRING(0 0, 150 60, 150 -60, 0 20)"
    for conf in (None, "Observed"):
        for label, wkt in (("straight", straight), ("curved", curved),
                           ("self-crossing", crossing)):
            out, err = evaluate(_inj.WAVE_EXPR, wkt, conf)
            check(err is None, "%s/%s line: %s" % (conf, label, err))
            if not check(not is_blank(out),
                         "%s/%s line produces geometry" % (conf, label)):
                continue
            check(len(list(out.parts())) == 1,
                  "%s/%s waves continuously, one part" % (conf, label))

    out, err = evaluate(_inj.WAVE_EXPR, straight, "Observed")
    if not is_blank(out):
        pts = list(out.vertices())
        check(len(pts) > 2,
              "the straight line gained vertices (%d)" % len(pts))
        dev = max(abs(p.y()) for p in pts)
        check(dev > 0, "and actually deviates from y=0 (%.3f)" % dev)

    # Inferred: whole tildes, phase-locked by construction.  A 235 m line
    # at tilde 50 m / step 75 m yields exactly 0-50, 75-125, 150-200.
    for conf in ("Inferred", "Queried"):
        out, err = evaluate(_inj.WAVE_EXPR, straight, conf)
        check(err is None, "%s tildes: %s" % (conf, err))
        if is_blank(out):
            check(False, "%s produces geometry" % conf)
            continue
        parts = list(out.parts())
        check(len(parts) == 3, "%s: 3 whole tildes on a 235 m line (%d)"
              % (conf, len(parts)))
        spans = sorted((min(p.x() for p in part.points()),
                        max(p.x() for p in part.points())) for part in parts)
        want = [(i * STEP, i * STEP + TILDE) for i in range(3)]
        ok = len(spans) == len(want) and all(
            abs(a - c) < 0.05 and abs(b - d) < 0.05
            for (a, b), (c, d) in zip(spans, want))
        check(ok, "%s: tildes sit at %s (got %s)" % (conf, want, spans))
        full_period = all(
            min(p.y() for p in part.points()) < -0.05
            and max(p.y() for p in part.points()) > 0.05
            for part in parts)
        check(full_period, "%s: every tilde carries a crest AND a trough"
              % conf)
        amp = max(abs(p.y()) for part in parts for p in part.points())
        want_amp = _inj.AMPLITUDE_MM / 1000.0 * REF_SCALE      # 3.5 m
        check(abs(amp - want_amp) < 0.35,
              "%s: amplitude is %.2f m of ground (want ~%.2f)"
              % (conf, amp, want_amp))

    # The whole point of round 3: the ground size follows the mapping
    # scale, so the same line at 1:10000 gets a wave twice as large.
    out, err = evaluate(_inj.WAVE_EXPR, straight, "Observed", scale=10000)
    if check(err is None and not is_blank(out), "wave at 1:10000: %s" % err):
        amp10k = max(abs(p.y()) for p in out.vertices())
        check(abs(amp10k - 2 * want_amp) < 0.7,
              "doubling the mapping scale doubles the ground wave "
              "(%.2f m vs %.2f)" % (amp10k, want_amp))

    out, err = evaluate(_inj.WAVE_EXPR, "LINESTRING(0 0, 40 0)", "Inferred")
    check(err is None and not is_blank(out)
          and len(list(out.parts())) == 1,
          "a line shorter than one tilde waves continuously instead")

    _, err = evaluate(_inj.WAVE_EXPR, "LINESTRING(50 50, 50 50)", "Observed")
    check(err is None, "zero-length line does not error (%s)" % err)


# ---------------------------------------------------------------------------
# 4. rendered
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


def reddish(c):
    return c.red() > 150 and c.green() < 120 and c.blue() < 120


def red_pixels(img):
    return [(x, y) for y in range(PX_H) for x in range(PX_W)
            if reddish(QColor(img.pixel(x, y)))]


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


def ink_runs(px, gap=3):
    """Contiguous x-runs of ink - one run per rendered tilde."""
    cols = sorted({x for x, _ in px})
    if not cols:
        return []
    runs, start, prev = [], cols[0], cols[0]
    for x in cols[1:]:
        if x - prev > gap:
            runs.append((start, prev))
            start = x
        prev = x
    runs.append((start, prev))
    return runs


def test_render(tmp_gpkg):
    print("render:")
    project = QgsProject.instance()
    # The ground-locked wave reads the mapping-scale variable that
    # script_setmapping.py publishes; without it the fallback applies.
    QgsExpressionContextUtils.setProjectVariable(
        project, "lgs_reference_scale", REF_SCALE)
    lw = QgsVectorLayer("%s|layername=%s" % (tmp_gpkg, _inj.LW), "lw", "ogr")
    if not check(lw.isValid(), "Linework opens"):
        return
    project.addMapLayer(lw)
    lw.setLabelsEnabled(False)
    lw.renderer().setReferenceScale(REF_SCALE)

    base = dict(Category="Structural", Type=_inj.CODE)
    seed(lw, mm_line(80), base)

    full = render(lw, REF_SCALE, project)
    observed_red = len(red_pixels(full))
    check(observed_red > 0, "the boundary draws red ink (%d px)"
          % observed_red)

    # The undulation claim needs the arrows out of the frame: strip the
    # MarkerLine from a working copy of the category symbol and measure the
    # vertical spread of what remains.  A straight 1.46 pt stroke is ~2 px
    # tall; a 0.7 mm amplitude adds ~2.6 px each side.
    renderer = lw.renderer()
    # categories() returns a temporary list; symbol() pointers into it
    # dangle the moment it dies, so keep it alive while cloning.
    cats = renderer.categories()
    idx = next(i for i, c in enumerate(cats) if c.value() == _inj.CODE)
    with_arrows = cats[idx].symbol().clone()
    del cats
    stroke_only = with_arrows.clone()
    while stroke_only.symbolLayerCount() > 1:
        stroke_only.deleteSymbolLayer(stroke_only.symbolLayerCount() - 1)
    renderer.updateCategorySymbol(idx, stroke_only)

    img = render(lw, REF_SCALE, project)
    px = red_pixels(img)
    if check(bool(px), "the bare stroke still draws"):
        ys = [y for _, y in px]
        spread = max(ys) - min(ys) + 1
        check(spread >= 5,
              "the stroke undulates: vertical spread %d px (straight "
              "would be ~2)" % spread)
    stroke_red = len(px)
    check(observed_red > stroke_red,
          "the arrows add ink beyond the bare stroke (%d > %d)"
          % (observed_red, stroke_red))

    # Inferred renders as separated whole tildes, still arrow-free here.
    seed(lw, mm_line(80), dict(base, Confidence="Inferred"))
    inf_img = render(lw, REF_SCALE, project)
    inf_px = red_pixels(inf_img)
    inferred_red = len(inf_px)
    seed(lw, mm_line(80), dict(base, Confidence="Observed"))
    solid_red = len(red_pixels(render(lw, REF_SCALE, project)))
    print("    red ink: observed=%d inferred=%d" % (solid_red, inferred_red))
    check(0 < inferred_red < solid_red * 0.85,
          "Inferred drops ink for the gaps (%d < %d)"
          % (inferred_red, solid_red))
    # Group inferred ink into contiguous x-runs: each is one tilde and
    # must carry BOTH a crest and a trough around the base line's y.
    runs = ink_runs(inf_px)
    print("    inferred tildes on screen: %d runs %s" % (len(runs), runs))
    check(len(runs) >= 3, "the dashes separate into tildes (%d runs)"
          % len(runs))
    cy = PX_H / 2.0
    whole = 0
    for lo, hi in runs:
        ys = [y for x, y in inf_px if lo <= x <= hi]
        if min(ys) < cy - 1.5 and max(ys) > cy + 1.5:
            whole += 1
    check(whole == len(runs),
          "every rendered dash is a whole ~ with crest and trough (%d/%d)"
          % (whole, len(runs)))

    # ---- the round-3 claim: the wave is locked to the ground ----------
    # Same feature, same reference scale, half the map scale.  A paper-mm
    # wave would keep its screen size and double its count; a ground-locked
    # one keeps its count and doubles on screen.
    seed(lw, mm_line(80), dict(base, Confidence="Inferred"))
    zoomed_px = red_pixels(render(lw, REF_SCALE / 2.0, project))
    zoom_runs = ink_runs(zoomed_px)
    print("    zoomed 2x: %d runs (was %d)" % (len(zoom_runs), len(runs)))
    check(len(zoom_runs) == len(runs),
          "zooming in does not add tildes: %d at 1:%d vs %d at 1:%d"
          % (len(zoom_runs), REF_SCALE / 2, len(runs), REF_SCALE))

    def spread(px):
        ys = [y for _, y in px]
        return (max(ys) - min(ys) + 1) if ys else 0

    s1, s2 = spread(inf_px), spread(zoomed_px)
    print("    vertical spread: 1:%d=%d px  1:%d=%d px"
          % (REF_SCALE, s1, REF_SCALE / 2, s2))
    check(s1 and 1.3 <= s2 / float(s1) <= 2.7,
          "the wave magnifies with the map (%d -> %d px, want ~2x)"
          % (s1, s2))

    # Weight thickening rides it too.
    seed(lw, mm_line(80), dict(base, Weight="Major"))
    major_red = len(red_pixels(render(lw, REF_SCALE, project)))
    check(major_red > solid_red,
          "Weight='Major' thickens the wavy stroke (%d > %d)"
          % (major_red, solid_red))

    renderer.updateCategorySymbol(idx, with_arrows)


# ---------------------------------------------------------------------------
# 5. idempotency
# ---------------------------------------------------------------------------

def qml_bytes(gpkg):
    con = sqlite3.connect(gpkg)
    try:
        return con.execute("SELECT styleQML FROM layer_styles "
                           "WHERE f_table_name=?", (_inj.LW,)).fetchone()[0]
    finally:
        con.close()


def test_idempotent(tmp_dir):
    print("idempotency:")
    work = os.path.join(tmp_dir, "idem.gpkg")
    shutil.copy2(GPKG, work)
    argv = sys.argv
    try:
        sys.argv = ["inject_linework_shear_wave.py", work]
        _inj.main()
        first = qml_bytes(work)
        _inj.main()
        second = qml_bytes(work)
    finally:
        sys.argv = argv
    check(first == second, "a second run leaves the QML byte-identical")
    check(_inj.GEN_ID in first, "and the generator is present")


def main():
    if not os.path.exists(GPKG):
        print("template not found: %s" % GPKG)
        return 2
    qgs = QgsApplication([], False)
    qgs.initQgis()
    tmp = tempfile.mkdtemp(prefix="lgs-shearwave-")
    try:
        work = os.path.join(tmp, "t.gpkg").replace("\\", "/")
        shutil.copy2(GPKG, work)
        test_structure()
        test_expressions_parse()
        test_wave_evaluates()
        test_render(work)
        test_idempotent(tmp)
    finally:
        QgsProject.instance().removeAllMapLayers()
        qgs.exitQgis()
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
