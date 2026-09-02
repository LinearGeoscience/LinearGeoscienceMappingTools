#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Labels must switch off once the view pulls far enough back.

Rounds 1 and 2 of the label work fixed how lettering LOOKS at any zoom and
said nothing about when it appears. The growth band actually made that worse:
inject_label_size_scaling.PAPER_F clamps the text at GROWTH_FLOOR on the way
out, so instead of fading into nothing it settles at 0.85x its authored size
and stays perfectly legible however far back you go. A 1:5000 project viewed
at 1:250,000 drew every label it had ever had, in a solid mat of text.

scripts/inject_label_scale_gate.py gives each labeling a data-defined
MinimumScale of LABEL_GATE_RATIO x the project's mapping scale, so the cutoff
travels with the scale someone is actually mapping at rather than being a
number that is right once. Major and Regional linework hold on twice as long -
the axial traces are the framework you still want named on an overview.

Checked three ways, on purpose:

  * the ARITHMETIC - each layer's real dd MinimumScale expression, evaluated
    across every reference scale Set Mapping Scale offers;
  * the ENGINE - actually rendering either side of the cutoff, because a
    correct expression on a property the label engine ignores would pass the
    arithmetic and do nothing (fontLimitPixelSize round-trips perfectly and
    has no effect on Point-unit fonts; that is exactly how this repo learned
    to stop trusting round-trips);
  * the PLUMBING - the reference scale reaches the expression as a runtime
    variable AND as a literal baked into the style, and both have to work.

The assertion that matters most is test 5. With NEITHER source available the
gate must not fire: an unknown scale means every label draws exactly as it did
before this existed. A gate that guesses would blank a whole map, which is a
far worse failure than the crowding it set out to fix - the same lesson as the
110 pt regression, where a missing reference scale was defaulted to 1:5000.

Run directly, or via the stdin-exec wrapper the other *_qgis tests use:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests/test_label_scale_gate_qgis.py
"""
import os
import re
import sqlite3
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem,  # noqa: E402
                       QgsExpression, QgsExpressionContext,
                       QgsExpressionContextUtils, QgsFeature, QgsGeometry,
                       QgsMapRendererParallelJob, QgsMapSettings,
                       QgsNullSymbolRenderer,
                       QgsPalLayerSettings, QgsPointXY, QgsProject,
                       QgsProperty, QgsRectangle, QgsTextFormat,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling, Qgis)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

from renderer_compat import (LABEL_GATE_RATIO,  # noqa: E402
                             LINEWORK_PERSIST_FACTOR,
                             label_scale_gate_expression)
from script_setmapping import (REFERENCE_SCALE_LITERAL_RE,  # noqa: E402
                               REFERENCE_SCALE_VAR)

REFERENCE_SCALES = (50, 500, 1000, 5000, 25000, 100000, 250000)

SIMPLE_LAYERS = ("2 - Linework", "3 - Overlay", "4 - Basemap")
FIELDNOTEBOOK = "1 - FieldNotebook"
FIELDNOTEBOOK_RULES = ("Dip Labels", "SymbolSuffix Labels",
                       "Fallback Labels (Comments/Labels)", "Regolith Note")
LINEWORK = "2 - Linework"

PERSIST_RATIO = LABEL_GATE_RATIO * LINEWORK_PERSIST_FACTOR

# Either side of the cutoff, as a multiple of it. Comfortably clear of the
# boundary itself - which side a label falls on exactly AT the cutoff is
# QGIS' business and not something worth pinning.
INSIDE = 0.9
OUTSIDE = 1.1

PX = 400
DPI = 96.0

# A label drawn at 20 pt covers far more than this; an empty frame covers
# nothing. The margin is wide enough that anti-aliasing cannot decide it.
INK_FLOOR = 40

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


# Loaded layers are cached because they must OUTLIVE anything taken out of
# them: layer.labeling() hands back a pointer the layer owns, so reading
# .settings() off a layer that has already been collected is a use-after-free
# and takes the interpreter down with an access violation rather than an
# exception.
_LAYERS = {}


def load(layer_name):
    if layer_name not in _LAYERS:
        layer = QgsVectorLayer("%s|layername=%s" % (TEMPLATE, layer_name),
                               layer_name, "ogr")
        if not layer.isValid():
            raise SystemExit("could not open %s" % layer_name)
        _LAYERS[layer_name] = layer
    return _LAYERS[layer_name]


def template_settings(layer_name):
    """The template's own QgsPalLayerSettings for a simple-labeled layer."""
    return QgsPalLayerSettings(load(layer_name).labeling().settings())


def gate_expression_of(settings):
    prop = settings.dataDefinedProperties().property(
        QgsPalLayerSettings.Property.MinimumScale)
    return prop.expressionString() if prop.isActive() else None


# Distinguishes "this layer's gate reads no fields, do not attach a feature"
# from "attach a feature whose Weight is NULL", which is a real case: an
# unrecorded Weight must fall to the ordinary cutoff, not to the long one.
NO_FEATURE = object()


def evaluate(expression_string, reference_scale, weight=NO_FEATURE,
             publish=True):
    """Evaluate a gate expression the way the label engine would."""
    ctx = QgsExpressionContext()
    ctx.appendScope(QgsExpressionContextUtils.globalScope())
    scope = QgsExpressionContextUtils.projectScope(QgsProject.instance())
    ctx.appendScope(scope)
    if publish:
        ctx.lastScope().setVariable(REFERENCE_SCALE_VAR, reference_scale)
    if weight is not NO_FEATURE:
        layer = QgsVectorLayer("Point?crs=EPSG:3857&field=Weight:string",
                               "probe", "memory")
        feature = QgsFeature(layer.fields())
        # Both of these are load-bearing: a QgsFeature that was never given
        # attributes and marked valid reports "no feature available" rather
        # than a NULL field, which is a different case entirely.
        feature.setAttributes([weight])
        feature.setValid(True)
        ctx.setFields(layer.fields())
        ctx.setFeature(feature)
    expression = QgsExpression(expression_string)
    value = expression.evaluate(ctx)
    if expression.hasEvalError():
        raise AssertionError("gate expression failed: %s"
                             % expression.evalErrorString())
    return value


# --------------------------------------------------------------------------
# Rendering. The gate is a property of the SETTINGS, so the probe keeps the
# template's scaleVisibility flag and its dd MinimumScale and replaces
# everything that would otherwise get in the way of seeing whether a label
# was drawn: the label text (the real grammar needs a populated feature), the
# placement (curved-on-line and fit-in-polygon both depend on geometry this
# probe does not have), and the dd Size (the real one lands around 5 pt at
# the cutoff, which is legible but a poor thing to threshold on).
# --------------------------------------------------------------------------

# Half the gap between two probe features, in metres. Small enough that both
# stay inside the view at the coarsest scale test 4 renders, wide enough that
# their 20 pt lettering never crosses the midline that separates them.
PROBE_OFFSET = 800.0


def probe_layer(settings, weights=("Minor",)):
    """A probe carrying the template's gate. Weight matters only on Linework,
    where Major and Regional take the longer cutoff; Minor is the ordinary
    case every layer shares, so it is the default."""
    layer = QgsVectorLayer("Point?crs=EPSG:3857&field=Weight:string",
                           "probe", "memory")
    features = []
    for i, weight in enumerate(weights):
        feature = QgsFeature(layer.fields())
        feature.setAttribute("Weight", weight)
        offset = (i - (len(weights) - 1) / 2.0) * 2 * PROBE_OFFSET
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(offset, 0.0)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()

    settings = QgsPalLayerSettings(settings)
    settings.fieldName = "'XXXXXX'"
    settings.isExpression = True
    settings.placement = Qgis.LabelPlacement.OverPoint
    fmt = QgsTextFormat()
    fmt.setSize(20)
    fmt.setColor(QColor(0, 0, 0))
    settings.setFormat(fmt)
    props = settings.dataDefinedProperties()
    props.setProperty(QgsPalLayerSettings.Property.Size, QgsProperty())
    settings.setDataDefinedProperties(props)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    # Nothing but lettering may put ink on this frame. With the default
    # marker still drawing, "gone" reads as a handful of pixels rather than
    # zero and the threshold has to guess which is which.
    layer.setRenderer(QgsNullSymbolRenderer())
    # The gate reads the published reference scale, never the renderer's, so
    # leaving this at 0 keeps the probe text a constant 20 pt at every zoom
    # and removes the size multiplier from the measurement entirely.
    layer.renderer().setReferenceScale(0)
    return layer


def ink(layer, map_scale, reference_scale, publish=True, halves=False):
    """Non-background pixels after rendering at `map_scale`."""
    ms = QgsMapSettings()
    ms.setLayers([layer])
    ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    ms.setOutputSize(QSize(PX, PX))
    ms.setOutputDpi(DPI)
    ms.setBackgroundColor(QColor(255, 255, 255))
    half = map_scale * (PX / DPI) * 0.0254 / 2.0
    ms.setExtent(QgsRectangle(-half, -half, half, half))

    project = QgsProject.instance()
    if publish:
        QgsExpressionContextUtils.setProjectVariable(
            project, REFERENCE_SCALE_VAR, reference_scale)
    else:
        QgsExpressionContextUtils.removeProjectVariable(
            project, REFERENCE_SCALE_VAR)

    # A bare QgsMapSettings carries NO expression context - not even
    # @map_scale. Without this the coalesce guard degrades, the gate never
    # fires, and every check here passes for the wrong reason.
    ctx = QgsExpressionContext()
    ctx.appendScope(QgsExpressionContextUtils.globalScope())
    ctx.appendScope(QgsExpressionContextUtils.projectScope(project))
    ctx.appendScope(QgsExpressionContextUtils.mapSettingsScope(ms))
    ms.setExpressionContext(ctx)

    job = QgsMapRendererParallelJob(ms)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()
    white = QColor(255, 255, 255)
    left = right = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if image.pixelColor(x, y) != white:
                if x < image.width() // 2:
                    left += 1
                else:
                    right += 1
    return (left, right) if halves else left + right


# --------------------------------------------------------------------------

def test_the_cutoff_tracks_the_mapping_scale():
    print("\n1. the cutoff is a ratio, at every mapping scale")
    for layer_name in SIMPLE_LAYERS:
        expression = gate_expression_of(template_settings(layer_name))
        if not check(expression is not None,
                     "%s carries a dd MinimumScale" % layer_name):
            continue
        for reference in REFERENCE_SCALES:
            weight = "Minor" if layer_name == LINEWORK else NO_FEATURE
            got = evaluate(expression, reference, weight=weight)
            want = reference * LABEL_GATE_RATIO
            check(abs(got - want) < 0.001,
                  "%s at 1:%d cuts off at 1:%s, want 1:%d"
                  % (layer_name, reference, got, want))


def test_major_and_regional_linework_hold_on_longer():
    print("\n2. Major and Regional linework persist to %dx" % PERSIST_RATIO)
    expression = gate_expression_of(template_settings(LINEWORK))
    for reference in REFERENCE_SCALES:
        for weight, ratio in (("Major", PERSIST_RATIO),
                              ("Regional", PERSIST_RATIO),
                              ("Minor", LABEL_GATE_RATIO),
                              ("Very Minor", LABEL_GATE_RATIO),
                              (None, LABEL_GATE_RATIO)):
            got = evaluate(expression, reference, weight=weight)
            want = reference * ratio
            check(abs(got - want) < 0.001,
                  "Linework %r at 1:%d cuts off at 1:%s, want 1:%d"
                  % (weight, reference, got, want))


def test_the_engine_actually_stops_drawing():
    print("\n3. the label engine honours it, either side of the cutoff")
    for layer_name in SIMPLE_LAYERS:
        settings = template_settings(layer_name)
        layer = probe_layer(settings)
        for reference in (500, 5000, 100000):
            cutoff = reference * LABEL_GATE_RATIO
            drawn = ink(layer, cutoff * INSIDE, reference)
            gone = ink(layer, cutoff * OUTSIDE, reference)
            check(drawn > INK_FLOOR,
                  "%s at 1:%d (inside 1:%d) drew %d px, wanted a label"
                  % (layer_name, cutoff * INSIDE, cutoff, drawn))
            check(gone == 0,
                  "%s at 1:%d (past 1:%d) drew %d px, wanted nothing"
                  % (layer_name, cutoff * OUTSIDE, cutoff, gone))


def test_the_engine_keeps_the_regional_framework():
    print("\n4. between the two cutoffs, only Major/Regional survives")
    reference = 5000
    layer = probe_layer(template_settings(LINEWORK),
                        weights=("Minor", "Major"))
    between = reference * (LABEL_GATE_RATIO + PERSIST_RATIO) / 2.0
    minor, major = ink(layer, between, reference, halves=True)
    check(minor == 0,
          "Minor linework still lettered at 1:%d (%d px)" % (between, minor))
    check(major > INK_FLOOR,
          "Major linework lost at 1:%d, the overview needs it (%d px)"
          % (between, major))
    past = reference * PERSIST_RATIO * OUTSIDE
    minor, major = ink(layer, past, reference, halves=True)
    check(minor == 0 and major == 0,
          "something still lettered at 1:%d, past every cutoff (%d/%d px)"
          % (past, minor, major))


def test_an_unknown_reference_scale_never_gates():
    print("\n5. with no reference scale at all, nothing is hidden")
    # The one that would hurt. A gate that fires when it does not know the
    # scale blanks a map; the old behaviour is always the safe fallback.
    for layer_name in SIMPLE_LAYERS:
        layer = probe_layer(template_settings(layer_name))
        for map_scale in (10000, 250000, 1000000):
            drawn = ink(layer, map_scale, 0, publish=False)
            check(drawn > INK_FLOOR,
                  "%s hid its label at 1:%d with NO reference scale "
                  "published - unknown must mean no gate, not a guess"
                  % (layer_name, map_scale))


def test_the_baked_literal_carries_it_without_the_plugin():
    print("\n6. the literal baked into the style works on its own")
    # A project handed to someone without the plugin has no @lgs_reference
    # _scale; bake_reference_scale_into_styles() is what keeps it working.
    reference = 5000
    for layer_name in SIMPLE_LAYERS:
        settings = template_settings(layer_name)
        expression = gate_expression_of(settings)
        baked, count = REFERENCE_SCALE_LITERAL_RE.subn(
            lambda m: m.group(1) + str(reference) + m.group(3), expression)
        if not check(count > 0,
                     "%s gate has no bakeable literal - "
                     "REFERENCE_SCALE_LITERAL_RE cannot see it" % layer_name):
            continue
        props = settings.dataDefinedProperties()
        props.setProperty(QgsPalLayerSettings.Property.MinimumScale,
                          QgsProperty.fromExpression(baked))
        settings.setDataDefinedProperties(props)
        layer = probe_layer(settings)
        cutoff = reference * LABEL_GATE_RATIO
        drawn = ink(layer, cutoff * INSIDE, 0, publish=False)
        gone = ink(layer, cutoff * OUTSIDE, 0, publish=False)
        check(drawn > INK_FLOOR,
              "%s baked-literal label missing inside the cutoff" % layer_name)
        check(gone == 0,
              "%s baked literal did not gate with the variable absent (%d px)"
              % (layer_name, gone))


def test_the_template_is_wired_for_it():
    print("\n7. scaleVisibility on, statics out of the way, all four layers")
    con = sqlite3.connect("file:%s?mode=ro" % TEMPLATE.replace("\\", "/"),
                          uri=True)
    for layer_name in SIMPLE_LAYERS + (FIELDNOTEBOOK,):
        qml = con.execute(
            "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
            (layer_name,)).fetchone()[0]
        kind = "rule-based" if layer_name == FIELDNOTEBOOK else "simple"
        block = re.search(r'<labeling type="%s">.*?</labeling>' % kind,
                          qml, re.S).group(0)
        renderings = re.findall(r'<rendering[^>]*>', block)
        wanted = len(FIELDNOTEBOOK_RULES) if kind == "rule-based" else 1
        gated = [r for r in renderings if 'scaleVisibility="1"' in r]
        check(len(gated) >= wanted,
              "%s: %d of %d labelings have scaleVisibility on"
              % (layer_name, len(gated), wanted))
        for rendering in gated:
            # The dd is the single source of the number; a static left behind
            # would silently win wherever it is tighter.
            check('scaleMin="0"' in rendering and 'scaleMax="0"' in rendering,
                  "%s: a static scale limit survives alongside the dd: %s"
                  % (layer_name, rendering))
    con.close()


def test_fieldnotebook_matches_what_set_mapping_scale_rebuilds():
    print("\n8. the FieldNotebook gate survives Set Mapping Scale")
    # build_structural_labeling() rebuilds this labeling from four fresh
    # QgsPalLayerSettings, so a gate that only lived in the template would be
    # wiped the first time anyone set the scale.
    layer = load(FIELDNOTEBOOK)
    labeling = layer.labeling()
    rules = {r.description(): r.settings()
             for r in labeling.rootRule().children()}
    wanted = label_scale_gate_expression()
    for description in FIELDNOTEBOOK_RULES:
        if not check(description in rules, "rule %r present" % description):
            continue
        settings = rules[description]
        check(bool(settings.scaleVisibility),
              "%s: scaleVisibility off, the dd cutoff is inert" % description)
        check(gate_expression_of(settings) == wanted,
              "%s: gate is %r, code builds %r"
              % (description, gate_expression_of(settings), wanted))


def main():
    for test in (test_the_cutoff_tracks_the_mapping_scale,
                 test_major_and_regional_linework_hold_on_longer,
                 test_the_engine_actually_stops_drawing,
                 test_the_engine_keeps_the_regional_framework,
                 test_an_unknown_reference_scale_never_gates,
                 test_the_baked_literal_carries_it_without_the_plugin,
                 test_the_template_is_wired_for_it,
                 test_fieldnotebook_matches_what_set_mapping_scale_rebuilds):
        test()
    print("\n%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    if not os.path.exists(TEMPLATE):
        print("SKIP: template not found: " + TEMPLATE)
        sys.exit(0)
    if QgsApplication.instance() is None:
        QgsApplication.setPrefixPath(
            os.environ.get("QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"),
            True)
        _app = QgsApplication([], False)
        _app.initQgis()
    sys.exit(main())
