"""Calibrate a stroke width per texture tile; write stroke_widths.tsv.

WHY THIS EXISTS
---------------
The 73 authored tiles were drawn at wildly different line densities, and they
all declare the same `stroke-width="param(outline-width) 0.1"`. Rendered at
one shared stroke width the set falls apart at both ends:

    svgStrokeWidth      0.3 pt      1.0 pt
    sandstone (dots)      0 px      2016 px      <- invisible until 1.0
    hornfels  (dots)      0 px      3122 px      <- invisible until 1.0
    slate     (lines)  9768 px     11088 px      <- 84% ink already at 0.3

Dot tiles vanish because a dot's whole visible size IS its stroke width, so
below ~1 pt it is sub-pixel; meanwhile the dense line tiles are already solid
mud. No single value serves both - the spread is about 35x.

So stroke width becomes the third data-defined property on the SVGFill
(alongside the tile and its colour), and this script measures the value each
tile needs to land near a common ink density. Rendering is done through the
real QGIS pipeline at the reference scale, so the numbers describe what the
map will actually do.

Ink fraction is scale-invariant in practice: tile width and stroke width are
both Point units, so referencescale multiplies them together and the ratio
holds as you zoom.

Run:  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" scripts/calibrate_lith_strokes.py
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import inject_basemap_lith_patterns as inj  # noqa: E402

OUT = os.path.join(REPO, "Template", "patterns", "stroke_widths.tsv")

TARGET_INK = 0.08       # fraction of the polygon covered by SOLID texture
# Ink is counted with a FIRM threshold, not "anything off-white". A stroke
# thinner than about one device pixel still tints a row of pixels, so a loose
# threshold scores it as inked while the map shows a barely-there ghost -
# that is how limestone first calibrated to "11% ink" and rendered invisible
# over its fill.
INK_LIGHTNESS = 170
WIDTH_MIN = 0.04
WIDTH_MAX = 4.0
CELL_W, CELL_H = 150, 100
PW, PH = 132, 88


def main():
    tiles = inj.load_tiles()

    from qgis.core import (QgsApplication, QgsVectorLayer, QgsFeature,
                           QgsGeometry, QgsFillSymbol, QgsLineSymbol,
                           QgsSVGFillSymbolLayer, QgsSingleSymbolRenderer,
                           QgsMapSettings, QgsRectangle, QgsUnitTypes,
                           QgsCoordinateReferenceSystem,
                           QgsMapRendererCustomPainterJob)
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QImage, QPainter, QColor

    QgsApplication.setPrefixPath(os.environ.get(
        "QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    result = {}
    try:
        def ink(tile, width):
            lyr = QgsVectorLayer("Polygon?crs=EPSG:3857&field=c:string",
                                 "t", "memory")
            f = QgsFeature(lyr.fields())
            f.setAttribute("c", "X")
            f.setGeometry(QgsGeometry.fromWkt(
                "POLYGON((0 0,%d 0,%d %d,0 %d,0 0))"
                % (CELL_W, CELL_W, CELL_H, CELL_H)))
            lyr.dataProvider().addFeatures([f])
            lyr.updateExtents()
            sl = QgsSVGFillSymbolLayer(inj.b64(tiles[tile]),
                                       inj.TILE_WIDTH_PT, 0.0)
            sl.setPatternWidthUnit(QgsUnitTypes.RenderPoints)
            sl.setSvgStrokeWidth(width)
            sl.setSvgStrokeWidthUnit(QgsUnitTypes.RenderPoints)
            sl.setSvgStrokeColor(QColor(20, 20, 20))
            sl.setSubSymbol(QgsLineSymbol.createSimple({"line_style": "no"}))
            ren = QgsSingleSymbolRenderer(QgsFillSymbol([sl]))
            ren.setReferenceScale(inj.REFERENCE_SCALE)
            lyr.setRenderer(ren)
            ms = QgsMapSettings()
            ms.setLayers([lyr])
            ms.setExtent(QgsRectangle(0, 0, CELL_W, CELL_H))
            ms.setOutputSize(QSize(PW, PH))
            ms.setBackgroundColor(QColor(255, 255, 255))
            ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
            im = QImage(QSize(PW, PH), QImage.Format_ARGB32_Premultiplied)
            im.fill(QColor(255, 255, 255))
            p = QPainter(im)
            job = QgsMapRendererCustomPainterJob(ms, p)
            job.start()
            job.waitForFinished()
            p.end()
            n = sum(1 for y in range(PH) for x in range(PW)
                    if QColor(im.pixel(x, y)).lightness() < INK_LIGHTNESS)
            return n / float(PW * PH)

        names = sorted(t for t in tiles if t != inj.BLANK)
        for t in names:
            # Invariant: lo is known-too-thin, hi is known-thick-enough.
            # Return HI, never the midpoint. Ink is a step function for tiles
            # whose marks are near sub-pixel, so the midpoint can sit on the
            # invisible side of the step - that is how iron_formation first
            # calibrated to 0.0% ink, i.e. a texture that never draws.
            lo, hi = WIDTH_MIN, WIDTH_MAX
            for _ in range(15):
                mid = (lo + hi) / 2.0
                if ink(t, mid) < TARGET_INK:
                    lo = mid
                else:
                    hi = mid
            # Round UP. hi is the thinnest width known to hit the target, and
            # for tiles with a sharp sub-pixel step (limestone, mylonite)
            # rounding down by a thousandth drops straight back below it.
            w = math.ceil(hi * 1000.0) / 1000.0
            v = ink(t, w)
            if v <= 0.005:
                # even the thick end of the bracket draws nothing: walk up
                while w < WIDTH_MAX and v <= 0.005:
                    w = round(min(WIDTH_MAX, w * 1.6), 3)
                    v = ink(t, w)
            result[t] = (w, v)
    finally:
        app.exitQgis()
        del app

    blank = [t for t, (_w, v) in result.items() if v <= 0.005]
    if blank:
        raise SystemExit("ABORT: these tiles draw nothing at any width: "
                         + ", ".join(sorted(blank)))
    heavy = [(t, v) for t, (_w, v) in result.items() if v > TARGET_INK * 1.6]
    faint = [(t, v) for t, (_w, v) in result.items() if v < TARGET_INK * 0.6]

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Stroke width per texture, Point units, calibrated to ~%d%% ink.\n"
                 "# Regenerate with scripts/calibrate_lith_strokes.py.\n"
                 "# One shared width does NOT work: dot tiles are invisible below\n"
                 "# ~1.0 pt (a dot's size IS its stroke) while dense line tiles are\n"
                 "# already solid at 0.3 pt.\n" % round(TARGET_INK * 100))
        fh.write("texture\twidth_pt\tink_pct\n")
        for t in sorted(result):
            w, v = result[t]
            fh.write("%s\t%.3f\t%.1f\n" % (t, w, v * 100))

    print("calibrated %d tiles to ~%.0f%% ink -> %s"
          % (len(result), TARGET_INK * 100, OUT))
    for i, t in enumerate(sorted(result)):
        w, v = result[t]
        print("  %-16s %5.2f pt  %4.1f%%" % (t, w, v * 100),
              end="\n" if i % 3 == 2 else "")
    print()
    if heavy:
        print("\nTOO DENSE even at minimum width (will read as near-solid):")
        for t, v in sorted(heavy, key=lambda kv: -kv[1]):
            print("   %-16s %.0f%% ink" % (t, v * 100))
    if faint:
        print("\nTOO SPARSE even at maximum width:")
        for t, v in sorted(faint, key=lambda kv: kv[1]):
            print("   %-16s %.0f%% ink" % (t, v * 100))


if __name__ == "__main__":
    main()
