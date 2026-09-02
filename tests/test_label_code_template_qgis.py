#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The FieldNotebook labeling in the template must equal what the code builds.

Set Mapping Scale and the static mapping export both call
script_setmapping.build_structural_labeling(), which REPLACES the layer's
labeling wholesale. So any part of the template's rule-based labeling that
the builder does not reproduce is silently reverted the first time a user
runs either of them.

That is not hypothetical: the family-aware Point dip offsets baked by
scripts/inject_fieldnotebook_dip_label_offsets.py shipped while the builder
still wrote flat MapUnit offsets, so Set Mapping Scale moved every dip label
back to a distance authored for a 1:5000 design footprint.

Run directly, or via the stdin-exec wrapper the other *_qgis tests use:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests/test_label_code_template_qgis.py
"""
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
PARENT = os.path.dirname(REPO_ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
PKG = os.path.basename(REPO_ROOT)

import importlib  # noqa: E402

from qgis.core import (QgsApplication, QgsPalLayerSettings,  # noqa: E402
                       QgsRuleBasedLabeling, QgsVectorLayer)

setmapping = importlib.import_module(PKG + ".script_setmapping")

TEMPLATE = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")
LAYER = "1 - FieldNotebook"

# The template is authored at this scale (symbologyReferenceScale), so it is
# the scale at which the builder must reproduce it exactly.
SCALE = 5000

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


def norm(expr):
    """Compare expressions on meaning, not on how they were typed.

    The template's expressions were authored in the QGIS builder and carry
    its line breaks and indentation; the code writes the same logic on one
    line. Collapsing whitespace - including either side of a bracket - is
    safe for THESE expressions specifically: every string literal in the
    four FieldNotebook rules is a single bare token ('RegolithNote', 'X',
    'Structure', ''), so no literal's spacing can be altered. Do not reuse
    this on the Basemap label, whose literals carry HTML.
    """
    flat = " ".join((expr or "").split())
    return flat.replace("( ", "(").replace(" )", ")")


def norm_style(name):
    """QGIS records an upright face as 'Regular'; a bare QFont leaves the
    style name empty. Same face either way - italic and size are compared
    on their own, and any real face change (Light, Bold, Semilight) still
    shows up as a different name."""
    return name or "Regular"


def describe(settings):
    """Everything about a label rule that a user would notice changing."""
    fmt = settings.format()
    font = fmt.font()
    point = settings.pointSettings()
    callout = settings.callout()
    dd = settings.dataDefinedProperties()
    offset = dd.property(QgsPalLayerSettings.Property.OffsetXY)
    rotation = dd.property(QgsPalLayerSettings.Property.LabelRotation)
    ring = dd.property(QgsPalLayerSettings.Property.LabelDistance)
    max_ring = dd.property(QgsPalLayerSettings.Property.MaximumDistance)
    gate = dd.property(QgsPalLayerSettings.Property.MinimumScale)
    return {
        "fieldName": norm(settings.fieldName),
        "isExpression": settings.isExpression,
        "font": font.family(),
        "fontStyle": norm_style(font.styleName()),
        "italic": font.italic(),
        "size": round(fmt.size(), 4),
        "colour": fmt.color().name(),
        "buffer": fmt.buffer().enabled(),
        "mask": fmt.mask().enabled(),
        "placement": int(settings.placement),
        "offsetType": int(settings.offsetType),
        "dist": round(settings.dist, 4),
        "distUnits": int(settings.distUnits),
        "offsetUnits": int(settings.offsetUnits),
        "maxDistance": round(point.maximumDistance(), 4),
        "maxDistanceUnit": int(point.maximumDistanceUnit()),
        "overlap": int(settings.placementSettings().overlapHandling()),
        "obstacleFactor": round(settings.obstacleSettings().factor(), 4),
        "priority": settings.priority,
        "autoWrapLength": settings.autoWrapLength,
        "callout": bool(callout is not None and callout.enabled()),
        "offsetXY": norm(offset.expressionString()) if offset.isActive() else "",
        "rotation": norm(rotation.expressionString()) if rotation.isActive() else "",
        # The paper-constant leader ring: the template (injector) and the
        # Set-Mapping-Scale rebuild must carry the SAME expressions, or the
        # first rescale silently strips the zoom fix.
        "ddLabelDistance": norm(ring.expressionString()) if ring.isActive() else "",
        "ddMaximumDistance": norm(max_ring.expressionString()) if max_ring.isActive() else "",
        # The zoom-out cutoff, for the same reason: the flag is inert without
        # the expression and the expression is inert without the flag, so a
        # rebuild that dropped either half would quietly bring back the mat
        # of text at 1:250,000 that scripts/inject_label_scale_gate.py exists
        # to stop.
        "scaleVisibility": bool(settings.scaleVisibility),
        "ddMinimumScale": norm(gate.expressionString()) if gate.isActive() else "",
    }


def rules_of(labeling):
    return {r.description(): r for r in labeling.rootRule().children()}


def main():
    if not os.path.exists(TEMPLATE):
        print("SKIP: template not found: " + TEMPLATE)
        return 0

    layer = QgsVectorLayer("%s|layername=%s" % (TEMPLATE, LAYER), LAYER, "ogr")
    if not check(layer.isValid(), "template layer loads"):
        return 1
    layer.loadDefaultStyle()

    baked = layer.labeling()
    if not check(isinstance(baked, QgsRuleBasedLabeling),
                 "template labeling is rule-based"):
        return 1

    built = setmapping.build_structural_labeling(SCALE)
    baked_rules = rules_of(baked)
    built_rules = rules_of(built)

    check(set(baked_rules) == set(built_rules),
          "same rule set (template %s vs code %s)"
          % (sorted(baked_rules), sorted(built_rules)))

    for desc in sorted(set(baked_rules) & set(built_rules)):
        a = baked_rules[desc]
        b = built_rules[desc]
        check(norm(a.filterExpression()) == norm(b.filterExpression()),
              "%s: filter\n    template: %s\n    code:     %s"
              % (desc, norm(a.filterExpression()), norm(b.filterExpression())))
        want = describe(a.settings())
        got = describe(b.settings())
        for key in sorted(want):
            check(want[key] == got[key],
                  "%s: %s - template %r, code %r"
                  % (desc, key, want[key], got[key]))

    # The specific regressions this file exists to catch.
    regolith = built_rules.get("Regolith Note")
    if regolith is not None:
        callout = regolith.settings().callout()
        check(callout is None or not callout.enabled(),
              "the code does not put a leader back on Regolith Notes")
    dip = built_rules.get("Dip Labels")
    if dip is not None:
        expr = dip.settings().dataDefinedProperties().property(
            QgsPalLayerSettings.Property.OffsetXY).expressionString()
        check("with_variable" in expr,
              "the code builds family-aware dip offsets, not a flat distance")

    print("%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    if QgsApplication.instance() is None:
        QgsApplication.setPrefixPath(
            os.environ.get("QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
        _app = QgsApplication([], False)
        _app.initQgis()
    sys.exit(main())
