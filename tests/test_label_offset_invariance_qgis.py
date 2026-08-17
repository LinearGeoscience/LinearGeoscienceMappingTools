#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A structural label must hold its position on its symbol at every zoom.

The FieldNotebook markers are 30 Point under a renderer reference scale, and
QGIS multiplies paper-unit SYMBOL sizes by referenceScale/mapScale - so the
marker keeps a constant GROUND footprint as you zoom (30 pt at 1:5000 spans
52.9 m). Label OFFSETS get no such treatment. Give the offset a paper unit
and the symbol grows underneath a label that does not, so the label slides
across it as you zoom.

This is the invariant that tests/test_label_code_template_qgis.py cannot
check: that one compares the builder against the template at a single scale,
and when both sides agree on the wrong unit it passes happily. Harry found
the drift by zooming, which is exactly what this file does.

Measurement: render one point twice per scale - once with labels off, once
with labels on and the text recoloured - and diff the two images. The pixels
that changed are the label. Then compare the label's distance from its point
against the symbol's rendered size; the RATIO is what must hold.

Run directly, or via the stdin-exec wrapper the other *_qgis tests use:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests/test_label_offset_invariance_qgis.py
"""
import math
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
LAYER = "1 - FieldNotebook"

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem,  # noqa: E402
                       QgsFeature, QgsGeometry, QgsMapRendererParallelJob,
                       QgsMapSettings, QgsPalLayerSettings, QgsPointXY,
                       QgsRectangle, QgsRuleBasedLabeling, QgsVectorLayer)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

# The template's authored reference scale. Held FIXED while the map scale
# changes - that is the zoom the user actually does.
REFERENCE_SCALE = 5000
MAP_SCALES = (5000, 2500, 1000, 500)

PX = 700
DPI = 96.0

# One planar code (label hugs the dip tick) and one linear code (label
# clears a plunge arrow) - they take different offsets, so a units bug can
# hide in one and not the other.
CASES = [
    ("S0", "planar"),
    ("LNS", "linear"),
]

# Ratio spread we accept across the whole zoom range. Anti-aliasing and
# glyph hinting move the measured centroid by a pixel or so at the small
# end; anything unit-related is a factor, not a percent.
TOLERANCE = 0.06

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


def build_layer(template_layer, code):
    """A one-point memory layer wearing the template's renderer + labeling."""
    mem = QgsVectorLayer(
        "Point?crs=EPSG:3857&field=Type:string&field=Subtype1:string"
        "&field=Dip:string&field=DipDirection:integer"
        "&field=SymbolSuffix:string&field=HidePoint:string"
        "&field=Confidence:string", "probe", "memory")
    feat = QgsFeature(mem.fields())
    feat.setAttribute("Type", "Structure")
    feat.setAttribute("Subtype1", code)
    feat.setAttribute("Dip", "62")
    # 90 puts the offset on the +x axis, so the measurement is a clean
    # horizontal distance rather than a diagonal.
    feat.setAttribute("DipDirection", 90)
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0, 0)))
    mem.dataProvider().addFeatures([feat])
    mem.updateExtents()

    mem.setRenderer(template_layer.renderer().clone())
    mem.renderer().setReferenceScale(REFERENCE_SCALE)

    labeling = template_layer.labeling().clone()
    # Keep only the Dip rule, and paint it a colour no symbol uses so the
    # image diff can find it even where it lands on top of the marker.
    root = labeling.rootRule()
    for rule in list(root.children()):
        if rule.description() != "Dip Labels":
            root.removeChildAt(root.children().index(rule))
    dip = root.children()[0]
    settings = QgsPalLayerSettings(dip.settings())
    fmt = settings.format()
    fmt.setColor(QColor(255, 0, 0))
    fmt.buffer().setEnabled(False)
    settings.setFormat(fmt)
    dip.setSettings(settings)
    mem.setLabeling(labeling)
    mem.setLabelsEnabled(True)
    return mem


def render(layer, scale, labels):
    ground = PX / DPI * 0.0254 * scale  # metres across the image
    half = ground / 2.0
    ms = QgsMapSettings()
    ms.setLayers([layer])
    ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    ms.setExtent(QgsRectangle(-half, -half, half, half))
    ms.setOutputSize(QSize(PX, PX))
    ms.setOutputDpi(DPI)
    ms.setBackgroundColor(QColor(255, 255, 255))
    ms.setFlag(QgsMapSettings.Flag.Antialiasing, True)
    ms.setFlag(QgsMapSettings.Flag.DrawLabeling, labels)
    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    return job.renderedImage(), ms.scale()


def measure(layer, scale):
    """Return (symbol_px, label_offset_px) at this map scale."""
    plain, got = render(layer, scale, labels=False)
    lettered, _ = render(layer, scale, labels=True)

    white = QColor(255, 255, 255).rgb()
    sxs, sys_, lxs, lys = [], [], [], []
    for y in range(PX):
        for x in range(PX):
            a = plain.pixel(x, y)
            if a != white:
                sxs.append(x)
                sys_.append(y)
            if lettered.pixel(x, y) != a:
                lxs.append(x)
                lys.append(y)

    if not sxs or not lxs:
        return None, None, got
    symbol_px = max(max(sxs) - min(sxs), max(sys_) - min(sys_)) + 1
    cx = sum(lxs) / float(len(lxs))
    cy = sum(lys) / float(len(lys))
    centre = PX / 2.0
    offset_px = math.hypot(cx - centre, cy - centre)
    return symbol_px, offset_px, got


def main():
    if not os.path.exists(TEMPLATE):
        print("SKIP: template not found: " + TEMPLATE)
        return 0

    template_layer = QgsVectorLayer(
        "%s|layername=%s" % (TEMPLATE, LAYER), LAYER, "ogr")
    if not check(template_layer.isValid(), "template layer loads"):
        return 1
    template_layer.loadDefaultStyle()
    if not check(isinstance(template_layer.labeling(), QgsRuleBasedLabeling),
                 "template labeling is rule-based"):
        return 1

    for code, family in CASES:
        layer = build_layer(template_layer, code)
        print("%s (%s), reference scale 1:%d" % (code, family, REFERENCE_SCALE))
        ratios = []
        for scale in MAP_SCALES:
            symbol_px, offset_px, got = measure(layer, scale)
            if not check(symbol_px is not None,
                         "%s: something rendered at 1:%d" % (code, scale)):
                continue
            check(abs(got - scale) / scale < 0.01,
                  "%s: map scale is 1:%d (got 1:%d)" % (code, scale, round(got)))
            ratio = offset_px / float(symbol_px)
            ratios.append(ratio)
            print("  1:%-5d symbol %4d px   label offset %6.1f px   "
                  "offset/symbol %.4f" % (scale, symbol_px, offset_px, ratio))

        if len(ratios) < 2:
            continue
        spread = (max(ratios) - min(ratios)) / max(ratios)
        check(spread <= TOLERANCE,
              "%s: label holds its place on the symbol across the zoom range "
              "(offset/symbol spread %.1f%%, tolerance %.0f%%; %s)"
              % (code, spread * 100, TOLERANCE * 100,
                 " ".join("%.4f" % r for r in ratios)))

    print("%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    if QgsApplication.instance() is None:
        QgsApplication.setPrefixPath(
            os.environ.get("QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
        _app = QgsApplication([], False)
        _app.initQgis()
    sys.exit(main())
