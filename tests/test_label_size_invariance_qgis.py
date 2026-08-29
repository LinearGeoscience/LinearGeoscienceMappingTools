#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Label text must hold its authored point size at every zoom.

QGIS multiplies EVERY rendered size by referenceScale/mapScale. Measured
against QgsRenderContext.convertToPainterUnits, Points, Millimeters, Pixels,
MapUnits, MetersInMapUnits and Inches all take the same factor, so there is no
unit to escape into. For symbols that is the point - a 30 pt structural marker
is meant to cover a fixed patch of ground. For lettering it is wrong: text has
to stay legible, not stay proportional. At a 1:100,000 reference scale a 5.5 pt
lithology label draws at 27 pt by the time you are in at 1:20,000, stops
fitting its polygon, gets pushed outside, and drags a leader across the map.

scripts/inject_label_size_scaling.py cancels the multiplier by dividing the
data-defined Size by the reference scale, read from @lgs_reference_scale.
This file is the proof, and it is a sibling of
tests/test_label_offset_invariance_qgis.py - same shape of bug, same shape of
test: hold one thing fixed, sweep the zoom, and assert what must not move.

Two things are checked in two different ways on purpose:

  * the ARITHMETIC, by evaluating each layer's real dd Size expression and
    pushing it through convertToPainterUnits - the same function the label
    engine calls - across every reference scale Set Mapping Scale offers; and
  * the ENGINE, by rendering labels at two map scales and measuring the
    glyphs, so a passing arithmetic model cannot cover for a label engine
    that ignores the expression.

'1 - FieldNotebook' must come through untouched. Its dip and suffix labels are
deliberately welded to their structural symbols, and the offsets that hold
them there are what test_label_offset_invariance_qgis.py protects.

Run directly, or via the stdin-exec wrapper the other *_qgis tests use:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests/test_label_size_invariance_qgis.py
"""
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem,  # noqa: E402
                       QgsExpression, QgsExpressionContext,
                       QgsExpressionContextUtils, QgsFeature, QgsGeometry,
                       QgsMapRendererParallelJob, QgsMapSettings,
                       QgsNullSymbolRenderer, QgsPalLayerSettings,
                       QgsPointXY, QgsProject, QgsRectangle,
                       QgsRenderContext, QgsVectorLayer, Qgis)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor, qGray  # noqa: E402

import inject_label_size_scaling as sizing  # noqa: E402
from script_setmapping import REFERENCE_SCALE_VAR  # noqa: E402

# Every reference scale Set Mapping Scale offers, ends included - the whole
# range has to work, not just the one the template happens to be baked at.
REFERENCE_SCALES = (50, 500, 1000, 5000, 25000, 100000, 250000)

# Zoom, as a multiple of the reference scale. 0.1x is well past what anyone
# does by hand and is where the old behaviour blew up by 10x.
ZOOM_FACTORS = (4.0, 2.0, 1.0, 0.5, 0.2, 0.1)

SIZED_LAYERS = ("2 - Linework", "3 - Overlay", "4 - Basemap")
WELDED_LAYER = "1 - FieldNotebook"

# Paper size is a float computation over a float expression; it should be
# exact to well within a thousandth. This is not an anti-aliasing tolerance.
TOLERANCE = 0.001

PX = 700
DPI = 96.0

_passed = 0
_failed = 0


def check(cond, label):
    global _passed, _failed
    if cond:
        _passed += 1
        print("  ok  : " + label)
    else:
        _failed += 1
        print("  FAIL: " + label)
    return cond


def load(layer_name):
    layer = QgsVectorLayer("%s|layername=%s" % (TEMPLATE, layer_name),
                           layer_name, "ogr")
    if not layer.isValid():
        raise SystemExit("could not open %s" % layer_name)
    return layer


def map_settings(scale):
    """A square view whose denominator is `scale`."""
    ms = QgsMapSettings()
    ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    ms.setOutputSize(QSize(PX, PX))
    ms.setOutputDpi(DPI)
    ground = scale * (PX / DPI) * 0.0254          # metres across the view
    ms.setExtent(QgsRectangle(0, 0, ground, ground))
    return ms


def paper_size(layer, settings, feature, reference_scale, map_scale,
               publish=True):
    """The point size this label actually lands on paper at this zoom.

    Evaluates the layer's own dd Size expression, then converts it the way
    QgsTextRenderer does, so the reference-scale multiplier is applied by
    QGIS rather than modelled here.
    """
    ms = map_settings(map_scale)
    ctx = QgsRenderContext.fromMapSettings(ms)
    ctx.setSymbologyReferenceScale(reference_scale)

    ectx = QgsExpressionContext()
    ectx.appendScope(QgsExpressionContextUtils.globalScope())
    ectx.appendScope(QgsExpressionContextUtils.mapSettingsScope(ms))
    # The layer scope is what resolves "Weight" / "TypeLith1" and friends;
    # the template layers ship empty, so the fields come from the schema
    # rather than from a row.
    ectx.appendScope(QgsExpressionContextUtils.layerScope(layer))
    if publish:
        ectx.lastScope().setVariable(REFERENCE_SCALE_VAR, reference_scale)
    ectx.setFields(layer.fields())
    if feature is not None:
        ectx.setFeature(feature)

    prop = settings.dataDefinedProperties().property(
        QgsPalLayerSettings.Property.Size)
    if prop.isActive():
        expression = QgsExpression(prop.expressionString())
        value = expression.evaluate(ectx)
        if expression.hasEvalError() or value is None:
            raise AssertionError("dd Size failed to evaluate: %s"
                                 % expression.evalErrorString())
        size = float(value)
    else:
        size = settings.format().size()

    painter_units = ctx.convertToPainterUnits(size, settings.format().sizeUnit())
    return painter_units / (DPI / 72.0)            # px back to points


# Side of the square the probe feature gets, in metres. Deliberately huge:
# EXTENT_F shrinks a label to 0.7x once its polygon is under 8 mm on screen,
# which is a scale-dependent factor ON PURPOSE. A 20 km square still measures
# 20 mm at 1:1,000,000, the coarsest view this sweep reaches, so EXTENT_F is
# pinned at 1 throughout and the only thing left free to move is the
# reference-scale factor this test exists to pin down.
PROBE_SIDE = 20000.0

# ... and the counterpart, small enough to be under 8 mm wherever it is used,
# so test 5 can prove EXTENT_F still does its job.
SMALL_SIDE = 1.0


def probe_feature(layer, side=PROBE_SIDE):
    """A feature carrying values for every field the size factors branch on."""
    feature = QgsFeature(layer.fields())
    feature.setAttributes([None] * len(layer.fields()))
    for name, value in (("Weight", "Major"), ("Width_cm", 3.0),
                        ("Type", "Fault"), ("Category", "Structural"),
                        ("TypeLith1", "Lithology"), ("Lithology1", "SST")):
        index = layer.fields().indexOf(name)
        if index >= 0:
            feature.setAttribute(index, value)
    feature.setGeometry(QgsGeometry.fromRect(
        QgsRectangle(0.0, 0.0, side, side)))
    feature.setValid(True)
    return feature


def test_paper_size_is_invariant():
    print("\n1. authored point size holds across the zoom range")
    for layer_name in SIZED_LAYERS:
        layer = load(layer_name)
        settings = QgsPalLayerSettings(layer.labeling().settings())
        feature = probe_feature(layer)
        authored = settings.format().size()

        for reference_scale in REFERENCE_SCALES:
            sizes = [paper_size(layer, settings, feature, reference_scale,
                                reference_scale * zoom)
                     for zoom in ZOOM_FACTORS]
            spread = (max(sizes) - min(sizes)) / max(sizes)
            check(spread <= TOLERANCE,
                  "%-14s ref 1:%-7d %5.2f pt at every zoom "
                  "(spread %.4f%%, %sx range)"
                  % (layer_name, reference_scale, sizes[0], spread * 100,
                     int(max(ZOOM_FACTORS) / min(ZOOM_FACTORS))))

            # At the reference scale itself the fix must be a no-op, or it
            # has quietly restyled every map that already read correctly.
            at_reference = paper_size(layer, settings, feature,
                                      reference_scale, reference_scale)
            check(abs(at_reference - sizes[ZOOM_FACTORS.index(1.0)]) < 1e-9
                  and at_reference > 0,
                  "%-14s ref 1:%-7d unchanged at the reference scale"
                  % (layer_name, reference_scale))

        # The authored static is what a geologist restyles in QGIS; the
        # expression is rebuilt from it, so the two must still agree.
        at_ref = paper_size(layer, settings, feature,
                            sizing.TEMPLATE_REFERENCE_SCALE,
                            sizing.TEMPLATE_REFERENCE_SCALE)
        check(0.5 * authored <= at_ref <= 2.0 * authored,
              "%-14s renders near its authored %.1f pt (got %.2f pt)"
              % (layer_name, authored, at_ref))


def test_small_polygons_still_shrink():
    """The deliberate scale-dependent factor must survive the fix.

    EXTENT_F shrinks a label whose polygon is under 8 mm on screen. It is the
    one thing here that is SUPPOSED to move with zoom, so a fix that flattened
    everything would break the cartography while passing test 1.
    """
    print("\n5. small polygons still label smaller")
    for layer_name in ("3 - Overlay", "4 - Basemap"):
        layer = load(layer_name)
        settings = QgsPalLayerSettings(layer.labeling().settings())
        big = paper_size(layer, settings, probe_feature(layer, PROBE_SIDE),
                         5000, 5000)
        small = paper_size(layer, settings, probe_feature(layer, SMALL_SIDE),
                           5000, 5000)
        check(small < big,
              "%-14s a sliver labels smaller than a big polygon "
              "(%.2f pt vs %.2f pt)" % (layer_name, small, big))


def test_a_missing_variable_degrades_to_the_old_behaviour():
    """No @lgs_reference_scale must mean NO compensation, never a guess.

    This is the case the rest of this file could not catch, because every
    other check sets the variable itself. It shipped once falling back to a
    constant 1:5000, so a project sitting at 1:100,000 with no variable was
    compensated as though it were at 1:5000 and drew every label at 110 pt -
    twenty times too big, and far worse than the bug being fixed.
    """
    print("\n6. a project with no variable is left alone, not guessed at")
    for layer_name in SIZED_LAYERS:
        layer = load(layer_name)
        settings = QgsPalLayerSettings(layer.labeling().settings())
        feature = probe_feature(layer)
        for reference_scale in (5000, 100000):
            # unset: paper_size() only sets the variable when asked to
            bare = paper_size(layer, settings, feature, reference_scale,
                              reference_scale, publish=False)
            published = paper_size(layer, settings, feature, reference_scale,
                                   reference_scale)
            check(abs(bare - published) < 0.01,
                  "%-14s ref 1:%-7d at the reference scale, variable or not, "
                  "%.2f pt either way" % (layer_name, reference_scale, bare))

            # Zoomed in 5x with no variable you should get the OLD behaviour
            # exactly - 5x too big. The shipped bug compensated by a constant
            # 1:5000 instead, which pinned the size at a flat 110 pt whatever
            # the zoom, so this ratio was 1.0 and not 5.0. That is the tell.
            zoomed = paper_size(layer, settings, feature, reference_scale,
                                reference_scale / 5.0, publish=False)
            ratio = zoomed / bare if bare else 0
            check(abs(ratio - 5.0) < 0.05,
                  "%-14s ref 1:%-7d no variable at 5x zoom grows 5x (%.2fx), "
                  "the old behaviour and no worse"
                  % (layer_name, reference_scale, ratio))


def test_fallback_matches_the_template():
    print("\n2. the baked fallback cannot drift from the template")
    for layer_name in SIZED_LAYERS + (WELDED_LAYER,):
        layer = load(layer_name)
        renderer = layer.renderer()
        check(renderer is not None
              and renderer.referenceScale() == sizing.TEMPLATE_REFERENCE_SCALE,
              "%-18s referencescale is %s, matching "
              "inject_label_size_scaling.TEMPLATE_REFERENCE_SCALE"
              % (layer_name, renderer.referenceScale() if renderer else None))


def test_fieldnotebook_is_untouched():
    print("\n3. the structural lettering is left alone")
    layer = load(WELDED_LAYER)
    labeling = layer.labeling()
    root = labeling.rootRule()
    rules = [r for r in root.children()]
    check(bool(rules), "%s still has its rule-based labeling" % WELDED_LAYER)
    for rule in rules:
        settings = rule.settings()
        if settings is None:
            continue
        prop = settings.dataDefinedProperties().property(
            QgsPalLayerSettings.Property.Size)
        expression = prop.expressionString() if prop.isActive() else ""
        check(REFERENCE_SCALE_VAR not in expression,
              "%-34s carries no paper factor - stays welded to its symbol"
              % ("'%s'" % rule.description()))


def render_label_height(layer_name, reference_scale, map_scale):
    """Tallest run of label ink, in pixels, with only labels drawn."""
    layer = load(layer_name)
    mem = QgsVectorLayer(
        "Polygon?crs=EPSG:3857&field=TypeLith1:string"
        "&field=Lithology1:string&field=LithologyPrefix:string", "probe",
        "memory")
    feature = QgsFeature(mem.fields())
    feature.setAttribute("TypeLith1", "Lithology")
    feature.setAttribute("Lithology1", "SST")
    ms = map_settings(map_scale)
    e = ms.extent()
    pad = e.width() * 0.25
    feature.setGeometry(QgsGeometry.fromRect(
        QgsRectangle(e.xMinimum() + pad, e.yMinimum() + pad,
                     e.xMaximum() - pad, e.yMaximum() - pad)))
    mem.dataProvider().addFeatures([feature])
    mem.updateExtents()

    labeling = layer.labeling().clone()
    settings = QgsPalLayerSettings(labeling.settings())
    fmt = settings.format()
    fmt.setColor(QColor(0, 0, 0))
    fmt.buffer().setEnabled(False)
    settings.setFormat(fmt)
    labeling.setSettings(settings)
    mem.setLabeling(labeling)
    mem.setLabelsEnabled(True)
    mem.setRenderer(QgsNullSymbolRenderer())
    mem.renderer().setReferenceScale(reference_scale)

    # Reach the engine the way the plugin does: the variable is published on
    # the project, and the render job reads it out of the map settings.
    #
    # A bare QgsMapSettings carries NO expression context - not even
    # @map_scale - so it has to be populated by hand here. The canvas does
    # this for itself, which is why the map draws correctly in QGIS. Miss it
    # and the paper factor's coalesce guard sees a NULL @map_scale and
    # degrades to 1, i.e. silently back to the old inflating behaviour, which
    # is exactly what this check is here to catch.
    project = QgsProject.instance()
    project.addMapLayer(mem, False)
    QgsExpressionContextUtils.setProjectVariable(
        project, REFERENCE_SCALE_VAR, reference_scale)

    ms.setLayers([mem])
    ms.setBackgroundColor(QColor(255, 255, 255))

    context = QgsExpressionContext()
    context.appendScope(QgsExpressionContextUtils.globalScope())
    context.appendScope(QgsExpressionContextUtils.projectScope(project))
    context.appendScope(QgsExpressionContextUtils.mapSettingsScope(ms))
    ms.setExpressionContext(context)

    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()
    project.removeMapLayer(mem.id())
    rows = [y for y in range(PX)
            if any(qGray(image.pixel(x, y)) < 128 for x in range(PX))]
    return (max(rows) - min(rows) + 1) if rows else 0


def test_the_engine_agrees():
    print("\n4. the label engine, not just the arithmetic")
    reference_scale = 100000
    heights = []
    for zoom in (1.0, 0.2):
        height = render_label_height("4 - Basemap", reference_scale,
                                     reference_scale * zoom)
        heights.append(height)
        print("    ref 1:%d viewed at 1:%d -> %d px of label"
              % (reference_scale, reference_scale * zoom, height))
    if not check(all(h > 0 for h in heights),
                 "labels actually rendered at both zooms"):
        return
    spread = abs(heights[0] - heights[1]) / float(max(heights))
    # Glyph hinting moves a rendered cap-height by a pixel; a units bug moves
    # it by the zoom factor, here 5x.
    check(spread <= 0.15,
          "rendered label height holds across a 5x zoom "
          "(%d px vs %d px, %.0f%% apart)"
          % (heights[0], heights[1], spread * 100))


def main():
    print("Template:", TEMPLATE)
    print("Fallback reference scale:", sizing.TEMPLATE_REFERENCE_SCALE)
    test_paper_size_is_invariant()
    test_fallback_matches_the_template()
    test_fieldnotebook_is_untouched()
    test_the_engine_agrees()
    test_small_polygons_still_shrink()
    test_a_missing_variable_degrades_to_the_old_behaviour()
    print("\n%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    if QgsApplication.instance() is None:
        QgsApplication.setPrefixPath(
            os.environ.get("QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
        _app = QgsApplication([], False)
        _app.initQgis()
    sys.exit(main())
