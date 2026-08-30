#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Label text must grow with the zoom, and then stop.

QGIS multiplies EVERY rendered size by referenceScale/mapScale. Measured
against QgsRenderContext.convertToPainterUnits, Points, Millimeters, Pixels,
MapUnits, MetersInMapUnits and Inches all take the same factor, so there is no
unit to escape into. For symbols that is the point - a 30 pt structural marker
is meant to cover a fixed patch of ground. For lettering it is wrong: text has
to stay legible, not stay proportional. At a 1:100,000 reference scale a 5.5 pt
lithology label draws at 27 pt by the time you are in at 1:20,000, stops
fitting its polygon, gets pushed outside, and drags a leader across the map.

scripts/inject_label_size_scaling.py reins that in: the size on the page is
`authored x clamp(GROWTH_FLOOR, referenceScale/mapScale, GROWTH_CEIL)`, so the
lettering keeps pace with the textures and linework around it for a while and
then holds. This file is the proof, and a sibling of
tests/test_label_offset_invariance_qgis.py - same shape of bug, same shape of
test: hold one thing fixed, sweep the zoom, and assert what must not move.

Three things are checked in three different ways on purpose:

  * the ARITHMETIC, by evaluating each layer's real dd Size expression and
    pushing it through convertToPainterUnits - the same function the label
    engine calls - across every reference scale Set Mapping Scale offers;
  * the ENGINE, by rendering labels at two map scales and measuring the
    glyphs, so a passing arithmetic model cannot cover for a label engine
    that ignores the expression; and
  * the PLUMBING, because the reference scale reaches the expression two
    ways and both have to work. @lgs_reference_scale is published at runtime
    and only exists while the plugin is loaded; the literal baked into the
    style is what carries a project handed to someone without it. With
    NEITHER, the factor must be 1 - the old behaviour - and never a guess:
    defaulting to a constant 1:5000 once drew every label on a 1:100,000
    sheet at 110 pt, twenty times too big.

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
                       QgsProperty,
                       QgsPointXY, QgsProject, QgsRectangle,
                       QgsRenderContext, QgsVectorLayer, Qgis)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor, qGray  # noqa: E402

import inject_label_size_scaling as sizing  # noqa: E402
import script_setmapping as setmapping  # noqa: E402
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


def expected_growth(reference_scale, map_scale):
    """clamp(FLOOR, M, CEIL), the multiple of the authored size we want."""
    multiplier = reference_scale / float(map_scale)
    return min(sizing.GROWTH_CEIL, max(sizing.GROWTH_FLOOR, multiplier))


def test_the_growth_band_holds():
    print("\n1. text grows with the zoom, then stops")
    for layer_name in SIZED_LAYERS:
        layer = load(layer_name)
        settings = QgsPalLayerSettings(layer.labeling().settings())
        feature = probe_feature(layer)

        for reference_scale in REFERENCE_SCALES:
            # At the reference scale the band is 1x, so this is the authored
            # size carried through the layer's other factors - the yardstick
            # every other zoom is measured against.
            at_reference = paper_size(layer, settings, feature,
                                      reference_scale, reference_scale)
            for zoom in ZOOM_FACTORS:
                got = paper_size(layer, settings, feature, reference_scale,
                                 reference_scale * zoom)
                want = at_reference * expected_growth(reference_scale,
                                                      reference_scale * zoom)
                ok = abs(got - want) <= max(want * TOLERANCE, 1e-6)
                if not ok or zoom in (1.0, min(ZOOM_FACTORS)):
                    check(ok, "%-14s ref 1:%-7d at %4sx zoom  %6.2f pt "
                               "(want %.2f, band %.2fx)"
                          % (layer_name, reference_scale, zoom, got, want,
                             expected_growth(reference_scale,
                                             reference_scale * zoom)))
                elif not ok:
                    check(False, "band broken")

            check(at_reference > 0,
                  "%-14s ref 1:%-7d %.2f pt at the reference scale - the fix "
                  "is a no-op where the map already read correctly"
                  % (layer_name, reference_scale, at_reference))

        # The authored static is what a geologist restyles in QGIS; the
        # expression is rebuilt from it, so the two must still agree.
        authored = settings.format().size()
        at_ref = paper_size(layer, settings, feature,
                            sizing.TEMPLATE_REFERENCE_SCALE,
                            sizing.TEMPLATE_REFERENCE_SCALE)
        check(0.5 * authored <= at_ref <= 2.0 * authored,
              "%-14s renders near its authored %.1f pt (got %.2f pt)"
              % (layer_name, authored, at_ref))


def test_the_baked_literal_works_without_the_variable():
    """A project handed to someone without the plugin must still be right.

    The project variable only exists while the plugin is loaded to publish
    it. script_setmapping bakes the same number into the style as a literal,
    so this is the path a shared .qgz actually takes.
    """
    print("\n7. the baked literal carries a project with no plugin")
    pattern = setmapping.REFERENCE_SCALE_LITERAL_RE
    for layer_name in SIZED_LAYERS:
        layer = load(layer_name)
        settings = QgsPalLayerSettings(layer.labeling().settings())
        prop = settings.dataDefinedProperties().property(
            QgsPalLayerSettings.Property.Size)
        baked = prop.expressionString()

        found = pattern.findall(baked)
        check(bool(found),
              "%-14s the injector's literal is where script_setmapping looks "
              "for it (%d occurrence(s))" % (layer_name, len(found)))
        check(all(f[1] == "0" for f in found),
              "%-14s ships baked as 0, i.e. 'unknown, behave as before'"
              % layer_name)

        for reference_scale in (5000, 100000):
            rewritten = pattern.sub(
                lambda m: m.group(1) + str(reference_scale) + m.group(3), baked)
            p = settings.dataDefinedProperties()
            p.setProperty(QgsPalLayerSettings.Property.Size,
                          QgsProperty.fromExpression(rewritten))
            probe = QgsPalLayerSettings(settings)
            probe.setDataDefinedProperties(p)
            feature = probe_feature(layer)

            with_literal = paper_size(layer, probe, feature, reference_scale,
                                      reference_scale / 5.0, publish=False)
            with_variable = paper_size(layer, settings, feature,
                                       reference_scale, reference_scale / 5.0)
            check(abs(with_literal - with_variable) < 0.01,
                  "%-14s ref 1:%-7d literal alone matches the variable "
                  "(%.2f pt vs %.2f pt)"
                  % (layer_name, reference_scale, with_literal, with_variable))


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


class _StubConfigurator(object):
    """Just enough of LayerConfigurator to drive one method of it."""

    def __init__(self, project):
        self.project = project

    def get_layer(self, layer_id):
        return self.project.mapLayer(layer_id)


def test_set_mapping_scale_bakes_the_literal():
    """The real method, on real layers: export, rewrite, import.

    Test 7 proves the arithmetic of the literal; this proves the machinery
    that writes it. The risk here is not the regex but importNamedStyle -
    the rewrite goes through QGIS' own style serialisation, and a renderer
    or a labeling block that failed to survive the round trip would take the
    whole layer's styling with it.
    """
    print("\n8. Set Mapping Scale writes the literal into the live styles")
    project = QgsProject.instance()
    project.clear()
    layers = {}
    for name in (WELDED_LAYER,) + SIZED_LAYERS:
        layer = load(name)
        layer.loadDefaultStyle()
        project.addMapLayer(layer, False)
        layers[name] = layer

    stub = _StubConfigurator(project)
    ids = dict((name, layer.id()) for name, layer in layers.items())
    changed = setmapping.LayerConfigurator.bake_reference_scale_into_styles(
        stub, ids, 100000)
    # All four layers now carry the literal: the three SIZED_LAYERS in their
    # label Size, and FieldNotebook in the Fallback rule's paper-constant
    # LabelDistance/MaximumDistance ring (2026-08-30). The dip weld is still
    # protected - test_fieldnotebook_is_untouched pins that no FieldNotebook
    # SIZE expression reads the reference scale.
    check(changed == len(SIZED_LAYERS) + 1,
          "rewrote %d layers - the three sized layers plus %s's callout "
          "ring literal" % (changed, WELDED_LAYER))

    for name in SIZED_LAYERS:
        layer = layers[name]
        check(layer.labeling() is not None and layer.renderer() is not None,
              "%-14s kept its renderer and labeling through the round trip"
              % name)
        expression = layer.labeling().settings().dataDefinedProperties(
            ).property(QgsPalLayerSettings.Property.Size).expressionString()
        found = set(m[1] for m in
                    setmapping.REFERENCE_SCALE_LITERAL_RE.findall(expression))
        check(found == {"100000"},
              "%-14s literal now reads %s" % (name, sorted(found)))
    project.clear()


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
    # 5x in, the band is at its ceiling, so the engine should draw GROWTH_CEIL
    # times the reference-scale height - not 5x (no compensation at all) and
    # not 1x (a flat cancel). Glyph hinting moves a rendered cap-height by a
    # pixel, hence the generous tolerance on a 5 px measurement.
    want = heights[0] * sizing.GROWTH_CEIL
    off = abs(heights[1] - want) / float(want)
    check(off <= 0.20,
          "rendered label height follows the band across a 5x zoom "
          "(%d px -> %d px, want ~%.1f at the %.1fx ceiling)"
          % (heights[0], heights[1], want, sizing.GROWTH_CEIL))


def main():
    print("Template:", TEMPLATE)
    print("Fallback reference scale:", sizing.TEMPLATE_REFERENCE_SCALE)
    test_the_growth_band_holds()
    test_fallback_matches_the_template()
    test_fieldnotebook_is_untouched()
    test_the_engine_agrees()
    test_small_polygons_still_shrink()
    test_a_missing_variable_degrades_to_the_old_behaviour()
    test_the_baked_literal_works_without_the_variable()
    test_set_mapping_scale_bakes_the_literal()
    print("\n%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    if QgsApplication.instance() is None:
        QgsApplication.setPrefixPath(
            os.environ.get("QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
        _app = QgsApplication([], False)
        _app.initQgis()
    sys.exit(main())
