#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify the Basemap SVG texture fills (MUST run inside QGIS).

Covers the things that could silently rot:

  1. Every curated tile in Template/patterns/ actually RENDERS. The authored
     library drew stipple as zero-length <line> elements with a round
     linecap, which the SVG spec paints as a dot but Qt paints as nothing -
     15 of 73 source tiles were invisible. prepare_lith_patterns.py repairs
     them; this asserts the repair held.
  2. lith_textures.tsv is exactly 1:1 with BasemapCodes and every texture
     names a real tile. This is what stops a code silently losing its
     texture when someone edits the table.
  3. The renderer carries exactly ONE SVGFill, with BOTH data-defined
     properties on it. That is the whole performance argument: QGIS builds
     every class symbol on every render pass, so an SVGFill per category
     would cost ~50 ms/redraw with nothing on screen, against ~0.25 ms for a
     single data-defined one. Two expressions on one layer stay free; two
     layers would not.
  4. Different lithologies get different textures, in a colour that both
     separates from and belongs with the class fill.
  5. renderer_compat reads BOTH templates - categorized (live) and
     rule-based (patterns) - and never treats the texture rule as a class.

Run directly, or via the stdin-exec wrapper the other *_qgis tests use:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests/test_basemap_lith_patterns_qgis.py
"""

import base64
import collections
import os
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
                       QgsCoordinateReferenceSystem,
                       QgsMapRendererCustomPainterJob,
                       QgsCategorizedSymbolRenderer, QgsRuleBasedRenderer)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QImage, QPainter, QColor  # noqa: E402

renderer_compat = importlib.import_module(PKG + ".renderer_compat")
_inj = importlib.import_module("inject_basemap_lith_patterns")

ORIGINAL = _inj.ORIGINAL
TARGET = _inj.TARGET
PATTERN_DIR = _inj.PATTERN_DIR
LAYER = _inj.LAYER
BLANK = _inj.BLANK
PATTERN_MAX_SCALE = _inj.PATTERN_MAX_SCALE
seams = importlib.import_module("lith_tile_seams")
_prep = importlib.import_module("prepare_lith_patterns")

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


def render(layers, ext, w=800, h=800):
    ms = QgsMapSettings()
    ms.setLayers(layers)
    ms.setExtent(ext)
    ms.setOutputSize(QSize(w, h))
    ms.setBackgroundColor(QColor(255, 255, 255))
    ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    im = QImage(QSize(w, h), QImage.Format_ARGB32_Premultiplied)
    im.fill(QColor(255, 255, 255))
    p = QPainter(im)
    job = QgsMapRendererCustomPainterJob(ms, p)
    t = time.perf_counter()
    job.start()
    job.waitForFinished()
    dt = time.perf_counter() - t
    p.end()
    return im, dt, ms.scale()


def main():
    if not os.path.exists(TARGET):
        print("SKIP: %s not built - run "
              "scripts/inject_basemap_lith_patterns.py" % os.path.basename(TARGET))
        return 0

    tiles = _inj.load_tiles()

    # ---- 1. every curated tile renders --------------------------------
    print("tiles:")
    for name, svg in sorted(tiles.items()):
        b = "base64:" + base64.b64encode(svg.encode()).decode()
        img = QgsApplication.svgCache().svgAsImage(
            b, 72.0, QColor(0, 0, 0), QColor(0, 0, 0), 1.2, 1.0)[0]
        img = img.convertToFormat(QImage.Format_ARGB32)
        ink = sum(1 for y in range(img.height()) for x in range(img.width())
                  if QColor.fromRgba(img.pixel(x, y)).alpha() > 40
                  and QColor(img.pixel(x, y)).lightness() < 200)
        if name == BLANK:
            check(ink == 0, "%s renders nothing (it is the ELSE tile)" % name)
        else:
            check(ink > 0, "%s renders visible ink (zero-length dot repair)" % name)
            check("param(outline)" in svg,
                  "%s keeps param(outline) so the colour control stays live" % name)
    print("  %d textures + blank" % (len(tiles) - 1))

    # ---- 2. the mapping table is complete and valid -------------------
    con = sqlite3.connect("file:%s?mode=ro" % ORIGINAL.replace("\\", "/"), uri=True)
    code_rows = con.execute("SELECT Code, Description FROM BasemapCodes").fetchall()
    con.close()
    codes = [c for c, _d in code_rows]
    print("mapping:")
    try:
        tex_map = _inj.load_texture_map(codes, tiles)
        check(True, "lith_textures.tsv is 1:1 with BasemapCodes")
    except SystemExit as exc:
        tex_map = {}
        check(False, "lith_textures.tsv is 1:1 with BasemapCodes: %s" % exc)
    check(len(tex_map) == len(codes),
          "%d rows for %d codes" % (len(tex_map), len(codes)))
    used = {t for t, _n, _i, _v in tex_map.values()}
    check(used <= set(tiles), "every texture names a real tile")
    check(BLANK not in used,
          "no code is mapped to the empty tile (every lithology gets a texture)")
    print("  %d codes -> %d textures" % (len(tex_map), len(used)))

    # Stroke width is per-texture and calibrated, not shared: a dot's visible
    # size IS its stroke width, so one value leaves the stipple tiles
    # invisible while the dense line tiles go solid.
    try:
        widths = _inj.load_stroke_widths(tiles)
        check(True, "stroke_widths.tsv covers every tile")
    except SystemExit as exc:
        widths = {}
        check(False, "stroke_widths.tsv covers every tile: %s" % exc)
    if widths:
        check(min(widths.values()) > 0,
              "no texture is calibrated to a zero stroke width")
        check(max(widths.values()) / min(widths.values()) > 3,
              "widths genuinely vary per texture (spread %.0fx) - a shared "
              "width would break this set"
              % (max(widths.values()) / min(widths.values())))
        print("  stroke widths %.2f-%.2f pt across %d tiles"
              % (min(widths.values()), max(widths.values()), len(widths)))

    # ---- 3. exactly one SVGFill, carrying both properties --------------
    con = sqlite3.connect("file:%s?mode=ro" % TARGET.replace("\\", "/"), uri=True)
    qml = con.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                      (LAYER,)).fetchone()[0]
    con.close()
    n_svgfill = qml.count('class="SVGFill"')
    print("renderer:")
    check(n_svgfill == 1,
          "exactly 1 SVGFill in the whole renderer (found %d) - more than one "
          "reintroduces the per-symbol render tax" % n_svgfill)
    check('"file"' in qml or "name=\"file\"" in qml,
          "data-defined svgFile present")
    check("outlineColor" in qml, "data-defined stroke colour present")

    pat = QgsVectorLayer("%s|layername=%s" % (TARGET, LAYER), LAYER, "ogr")
    check(pat.isValid(), "patterns template layer opens")
    check(isinstance(pat.renderer(), QgsRuleBasedRenderer),
          "patterns template is rule-based")

    orig = QgsVectorLayer("%s|layername=%s" % (ORIGINAL, LAYER), LAYER, "ogr")
    check(orig.isValid(), "live template layer opens")
    check(isinstance(orig.renderer(), QgsCategorizedSymbolRenderer),
          "live template is STILL categorized (must not be modified)")

    # ---- 4. renderer_compat reads both, hides the texture rule --------
    print("renderer_compat:")
    for tag, layer in (("live", orig), ("patterns", pat)):
        classes = renderer_compat.renderer_classes(layer.renderer())
        check(len(classes) == 300,
              "%s: %d classes (expected 300)" % (tag, len(classes)))
        check(renderer_compat.class_attribute(layer.renderer()) == "Lithology1",
              "%s: class attribute resolves to Lithology1" % tag)
        check(renderer_compat.PATTERN_RULE_LABEL not in [v for v, _s in classes],
              "%s: texture rule is not exposed as a class" % tag)
    removed, kept, new = renderer_compat.prune_classes(pat.renderer(),
                                                       lambda v: False)
    check(removed == 300 and kept == 0,
          "pruning everything removes all 300 classes (got %d/%d)" % (removed, kept))
    if new is not None:
        survivors = [r for r in new.rootRule().children()
                     if renderer_compat.is_pattern_rule(r)]
        check(len(survivors) == 1,
              "the texture rule survives a total prune (found %d)" % len(survivors))

    # ---- 5. tinted colours all meet the contrast target ---------------
    fill_of = {}
    for c in orig.renderer().categories():
        v = c.value()
        if v is None or str(v).strip() in ("", "NULL") or c.symbol() is None:
            continue
        col = c.symbol().color()
        fill_of[str(v)] = (col.red(), col.green(), col.blue())
    print("colour:")
    # The contrast target is PER TEXTURE now, scaled by that tile's measured
    # ink coverage, so there is no single number every tint must reach. What
    # must hold is that each code clears its OWN target's floor - and that the
    # heavy tiles really are aimed softer than the sparse ones, which is the
    # whole point of the change.
    tile_ink = _inj.load_tile_ink(tiles)
    worst_gap, worst_code, lighter, below = 0.0, None, 0, []
    for code, (texture, _n, ink_name, _v) in tex_map.items():
        fill = fill_of.get(code)
        if fill is None or ink_name != "auto":
            continue
        target = _inj.target_for_ink_pct(tile_ink[texture])
        _rgb, ratio, direction = _inj.tint(fill, target)
        if direction == "lighter":
            lighter += 1
        floor = max(_inj.WEAK_INK_FLOOR, target * _inj.WEAK_INK_MARGIN)
        if ratio < floor:
            below.append((code, ratio, floor))
        if target - ratio > worst_gap:
            worst_gap, worst_code = target - ratio, code
    check(not below,
          "every auto tint clears its own target's floor (%d below: %s)"
          % (len(below), below[:4]))
    heavy = max(tile_ink, key=lambda t: tile_ink[t])
    light = min(tile_ink, key=lambda t: tile_ink[t])
    t_heavy = _inj.target_for_ink_pct(tile_ink[heavy])
    t_light = _inj.target_for_ink_pct(tile_ink[light])
    if _inj.INK_FLOOR_RATIO >= 1.0:
        # Load scaling deliberately off: the calibrator already equalises ink
        # coverage, so scaling contrast by it penalised a second time the few
        # tiles it could not get down to 8%. Assert it really is flat rather
        # than silently sagging.
        check(abs(t_heavy - t_light) < 0.01
              and abs(t_light - _inj.INK_BASE) < 0.01,
              "every texture aims at INK_BASE %.2f (heaviest %s %.2f, "
              "lightest %s %.2f)"
              % (_inj.INK_BASE, heavy, t_heavy, light, t_light))
    # Proportional, not an absolute margin. The whole band scales with the
    # dial, so at a soft setting it is only ~0.26 wide and any fixed gap fails
    # while the mechanism is working perfectly well.
    check(_inj.INK_FLOOR_RATIO >= 1.0
          or _inj.target_for_ink_pct(tile_ink[heavy])
          < _inj.target_for_ink_pct(tile_ink[light]) * 0.92,
          "the heaviest tile (%s %.0f%% -> %.2f) is aimed softer than the "
          "lightest (%s %.0f%% -> %.2f)"
          % (heavy, tile_ink[heavy], _inj.target_for_ink_pct(tile_ink[heavy]),
             light, tile_ink[light], _inj.target_for_ink_pct(tile_ink[light])))
    check(lighter > 0,
          "dark fills still invert to a light texture (%d do) - a softer "
          "target must not silently make dark-on-dark reachable" % lighter)
    print("  %d fills, %d inverted to a light texture, %s"
          % (len(set(fill_of.values())), lighter,
             "every tint reaches its target exactly" if worst_code is None
             else "largest shortfall %.2f on %s" % (worst_gap, worst_code)))

    # ---- 5a. every tile tiles seamlessly ------------------------------
    # The defect this catches renders as a full-width stripe across the
    # polygon, because at referencescale 5000 and 1:200-1:500 the 12 pt tile
    # is drawn 120-300 pt wide. See scripts/lith_tile_seams.py for why the
    # check is geometric and not a rendered ink metric.
    print("seams:")
    widths = _inj.load_stroke_widths(tiles)
    unsound = {}
    for texture in sorted(tiles):
        if texture == BLANK:
            continue
        path = os.path.join(PATTERN_DIR, texture + ".svg")
        with open(path, encoding="utf-8") as fh:
            issues = seams.audit(fh.read(), widths[texture])
        if issues:
            unsound[texture] = issues[0][1]
    check(not unsound,
          "every tile is toroidally sound (%d not: %s)"
          % (len(unsound), sorted(unsound)[:4]))
    for texture, msg in sorted(unsound.items()):
        print("  %-16s %s" % (texture, msg))

    # The reference implementations must keep passing: they carry their wrap
    # counterparts by hand, and a checker that flags them is wrong about what
    # seamless means.
    for texture in ("basalt", "evaporite", "schist", "mylonite"):
        path = os.path.join(PATTERN_DIR, texture + ".svg")
        with open(path, encoding="utf-8") as fh:
            check(not seams.audit(fh.read(), widths[texture]),
                  "%s - a hand-authored seamless tile - still passes"
                  % texture)

    # Blank-band regression pin. These are the tiles whose rhythm did not
    # divide their own period; the ratio is max motif-row gap over the median,
    # including the wrap. Pinned per tile rather than globally because a global
    # metric fires on tiles nobody intends to change - a quincunx legitimately
    # scores 2.0. See the rejected-metrics note in lith_tile_seams.
    for texture in sorted(_prep.RELATTICE) + sorted(_prep.RESIZE):
        path = os.path.join(PATTERN_DIR, texture + ".svg")
        with open(path, encoding="utf-8") as fh:
            svg = fh.read()
        W, H, els = seams.parse(svg)
        axis = _prep.RELATTICE.get(texture, "y")
        P, idx = (H, 1) if axis == "y" else (W, 0)
        vals = sorted({round(sum(p[idx] for p in seams.coords_of(el))
                             / len(seams.coords_of(el)), 3) for el in els})
        rows, cur = [], [vals[0]]
        for v in vals[1:]:
            if v - cur[-1] <= 1.0:
                cur.append(v)
            else:
                rows.append(cur)
                cur = [v]          # a fresh list: cur.clear() would empty the
        rows.append(cur)           # one just appended, they are the same object
        centres = [sum(r) / len(r) for r in rows]
        if len(centres) < 3:
            continue
        gaps = sorted([centres[i + 1] - centres[i]
                       for i in range(len(centres) - 1)]
                      + [centres[0] + P - centres[-1]])
        ratio = max(gaps) / max(gaps[len(gaps) // 2], 0.01)
        check(ratio <= 1.35,
              "%s has no blank band left (row-gap ratio %.2f)"
              % (texture, ratio))

    # ---- 5b. codes that could be mapped adjacent must not be identical
    # Round 3 checked that TEXTURES were distinct and reported that as
    # distinctness; it never checked CODES, and 218 of 283 shared an
    # identical (fill, ink, tile) triple. This is that missing assertion.
    import importlib as _il
    lith_palette = _il.import_module("lith_palette")
    fills, inks = {}, {}
    with open(os.path.join(PATTERN_DIR, "lith_fills.tsv"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("code") or not line.strip():
                continue
            c, f, i = line.rstrip("\n").split("\t")
            fills[c] = tuple(int(f.lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))
            inks[c] = tuple(int(i.lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))
    print("separation:")
    check(len(fills) == len(codes), "lith_fills.tsv covers every code")
    by_fam = {}
    for c in tex_map:
        by_fam.setdefault(lith_palette._family_of(c), []).append(c)
    identical = []
    for members in by_fam.values():
        members.sort()
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                va, vb = tex_map[a][3], tex_map[b][3]
                if va and va == vb:
                    continue
                if tex_map[a][0] != tex_map[b][0]:
                    continue
                if (_inj.delta_e(fills[a], fills[b]) < _inj.IDENTICAL_DE
                        and _inj.delta_e(inks[a], inks[b]) < _inj.IDENTICAL_DE):
                    identical.append((a, b))
    check(not identical,
          "no two different rocks render identically (%d pairs: %s)"
          % (len(identical), identical[:5]))
    check(len(set(fills.values())) > 150,
          "fills are genuinely varied (%d distinct)" % len(set(fills.values())))

    # sheared rocks carry their protolith's colour, not an ochre of their own
    old_ochre = (253, 184, 100)
    for c in sorted(x for x in fills if x.startswith("Z")):
        proto = lith_palette.PROTOLITH.get(c)
        if not proto:
            continue
        check(_inj.delta_e(fills[c], old_ochre) > 20,
              "%s no longer sits on the sheared ochre" % c)
    print("  %d distinct fills, %d identical pairs"
          % (len(set(fills.values())), len(identical)))

    # ---- 5c. the template's OWN palette must survive ------------------
    # These exist because a family-modal base flattened 48 real colours into
    # ~11: the felsic volcanics lost their yellow and the migmatite ramp
    # collapsed. Anchoring is per code now, and these assert it stays that way.
    anchors = lith_palette.read_code_anchors()
    print("template palette:")
    exact = [c for c, rgb in fills.items() if anchors.get(c) == rgb]
    check(len(exact) > 25,
          "codes with a unique original colour keep it exactly (%d do)"
          % len(exact))

    # felsic extrusive stays yellow, intrusive stays pink
    EXTRUSIVE = "FR FRD FIG FTA FTX FV FVC FVP FVX FP FQFP FQP FD".split()
    INTRUSIVE = "FGR FGD FGM FSY FTO FTJ FI FAB FGRL FGRB".split()

    def _hue(c):
        import colorsys as _cs
        return _cs.rgb_to_hls(*[x / 255.0 for x in fills[c]])[0] * 360.0
    ext_h = [_hue(c) for c in EXTRUSIVE if c in fills]
    int_h = [_hue(c) for c in INTRUSIVE if c in fills]
    check(all(35 <= h <= 65 for h in ext_h),
          "all felsic extrusives sit in the yellow band (%s)"
          % ", ".join("%s=%.0f" % (c, _hue(c))
                      for c in EXTRUSIVE if c in fills and not 35 <= _hue(c) <= 65))
    check(all(h >= 320 or h <= 20 for h in int_h),
          "all felsic intrusives sit in the pink band (%s)"
          % ", ".join("%s=%.0f" % (c, _hue(c))
                      for c in INTRUSIVE if c in fills
                      and not (_hue(c) >= 320 or _hue(c) <= 20)))
    check("FD" in fills and 35 <= _hue("FD") <= 65,
          "FD Dacite corrected to the extrusive yellow")
    check("FAB" in fills and (_hue("FAB") >= 320 or _hue("FAB") <= 20),
          "FAB Albitite corrected to the intrusive pink")

    # the migmatite ramp survives
    MIG = "HMIP HMIS HMIN HMIT HMI HMIM HMID".split()
    mig = [fills[c] for c in MIG if c in fills]
    check(len(set(mig)) == len(mig),
          "the %d migmatites keep distinct fills (%d distinct)"
          % (len(mig), len(set(mig))))
    if len(mig) > 1:
        spread = max(_inj.delta_e(a, b) for a in mig for b in mig)
        check(spread > 30,
              "the migmatite ramp still spans a real range (dE %.0f)" % spread)

    # felsic vs metamorphic: the complaint that opened this round
    fel = [c for c in fills if c.startswith("F")]
    # No exclusion any more. This used to skip the H codes whose PROTOLITH was
    # "F", because those were deliberately coloured AS felsic - which turned
    # out to be the bug: F's modal colour is the intrusive pink, so felsic
    # gneiss, felsic granulite and charnockite resolved to granitoid pink. They
    # now carry the terracotta gneiss colours instead, so every H code belongs
    # in this comparison and the check is strictly stronger than it was.
    met = [c for c in fills if c.startswith("H")]
    if fel and met:
        # Same rule the injector uses: a pair separates on colour OR on
        # texture. Judging colour alone here would be stricter than what the
        # map actually does.
        same_tex = [(_inj.delta_e(fills[a], fills[b]), a, b)
                    for a in fel for b in met
                    if tex_map[a][0] == tex_map[b][0]]
        worst = min(same_tex)[0] if same_tex else 99.0
        check(worst > 6.0,
              "felsic and metamorphic codes sharing a texture separate on "
              "colour (worst dE %.1f: %s)"
              % (worst, sorted(same_tex)[:2] if same_tex else "none"))
        any_worst = min(_inj.delta_e(fills[a], fills[b])
                        for a in fel for b in met)
        print("  %d exact, migmatite spread dE %.0f, F-vs-H worst dE %.1f "
              "(same-texture %.1f)" % (len(exact), spread, any_worst, worst))

    # ---- 6. textures actually differ, over their real fill ------------
    rep = {}
    for code, (texture, _note, _ink, _var) in tex_map.items():
        rep.setdefault(texture, code)
    names = sorted(rep)
    COLS = 7
    CELL = 100
    rowsn = (len(names) + COLS - 1) // COLS
    mem = QgsVectorLayer(
        "Polygon?crs=EPSG:3857&field=Lithology1:string&field=ContactType:string",
        "t", "memory")
    feats = []
    for i, m in enumerate(names):
        f = QgsFeature(mem.fields())
        f.setAttribute("Lithology1", rep[m])
        f.setAttribute("ContactType", "Solid")
        x, y = (i % COLS) * CELL, (i // COLS) * CELL
        f.setGeometry(QgsGeometry.fromWkt(
            "POLYGON((%d %d,%d %d,%d %d,%d %d,%d %d))"
            % (x, y, x + CELL, y, x + CELL, y + CELL, x, y + CELL, x, y)))
        feats.append(f)
    mem.dataProvider().addFeatures(feats)
    mem.updateExtents()
    mem.setRenderer(pat.renderer().clone())

    W, H = COLS * CELL, rowsn * CELL
    px = 2
    im, _dt, scale = render([mem], QgsRectangle(0, 0, W, H), W * px, H * px)
    print("textures (map scale 1:%d):" % round(scale))
    sigs = {}
    for i, m in enumerate(names):
        cx0 = (i % COLS) * CELL * px
        cy0 = (rowsn - 1 - i // COLS) * CELL * px
        pts = [(x, y) for y in range(cy0 + 12, cy0 + CELL * px - 12)
               for x in range(cx0 + 12, cx0 + CELL * px - 12)]
        counts = collections.Counter(im.pixel(x, y) for x, y in pts)
        base = QColor(counts.most_common(1)[0][0])
        ink = sum(1 for x, y in pts if im.pixel(x, y) != counts.most_common(1)[0][0])
        sigs[m] = ink
        check(ink > 0, "%s (%s) draws texture over its fill" % (m, rep[m]))
        check(base != QColor(255, 255, 255),
              "%s (%s) still shows its class fill colour" % (m, rep[m]))
    distinct = len(set(sigs.values()))
    check(distinct >= len(names) - 2,
          "textures are visually distinct (%d distinct signatures of %d)"
          % (distinct, len(names)))

    # ---- 7. scale gating ---------------------------------------------
    im_far, _dt, s_far = render([mem], QgsRectangle(0, 0, 40000, 40000), 400, 400)
    counts = collections.Counter(im_far.pixel(x, y)
                                 for y in range(150, 190) for x in range(10, 50))
    check(s_far > PATTERN_MAX_SCALE, "far view is beyond the texture cutoff")
    check(len(counts) == 1,
          "texture is off at 1:%d (cutoff 1:%d) - %d colours found"
          % (round(s_far), PATTERN_MAX_SCALE, len(counts)))

    # ---- 8. the texture must stay nearly free -------------------------
    EXT = QgsRectangle(0, 0, 1000, 1000)
    orig.setLabelsEnabled(False)
    pat.setLabelsEnabled(False)
    for _ in range(6):
        render([orig], EXT)
        render([pat], EXT)
    ta, tc = [], []
    for i in range(9):
        e = QgsRectangle(i * 7, i * 7, 1000 + i * 7, 1000 + i * 7)
        ta.append(render([orig], e)[1])
        tc.append(render([pat], e)[1])
    ta.sort()
    tc.sort()
    med_a, med_c = ta[len(ta) // 2] * 1000, tc[len(tc) // 2] * 1000
    print("redraw cost, 0 features: live %.2f ms, patterns %.2f ms (%+.2f ms)"
          % (med_a, med_c, med_c - med_a))
    check(med_c < med_a + 5.0,
          "textures add < 5 ms per redraw (added %+.2f ms)" % (med_c - med_a))

    print("\n%d checks passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    # Works either way: under the stdin-exec wrapper the other *_qgis tests
    # use (QgsApplication already up), or run directly against
    # python-qgis-ltr.bat, in which case bootstrap it here.
    _app = None
    if QgsApplication.instance() is None:
        QgsApplication.setPrefixPath(
            os.environ.get("QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
        _app = QgsApplication([], False)
        _app.initQgis()
    try:
        rc = main()
    finally:
        if _app is not None:
            _app.exitQgis()
            del _app
    sys.exit(rc)
