#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The baked cross-layer label placement ladder must hold in the template.

One explicit ladder governs who wins space when labels collide (higher
priority places first): Dip 10 > Suffix 8 > Basemap 6 > Linework 5 >
Overlay 4 > Fallback comments 3 > Regolith 2. Basemap must have shed its
AllowOverlapAtNoCost stamping for the mobile inside-preferred/short-leader
placement, Linework must never hide an annotation, and every FieldNotebook
rule must carry the raised labels-as-obstacles factor.

Baked by scripts/inject_basemap_label_placement.py and
scripts/inject_label_priority_ladder.py; the FieldNotebook side is also
rebuilt at runtime by script_setmapping.build_structural_labeling(), whose
equality with the template is enforced by test_label_code_template_qgis.py.
This file catches hand-re-authoring regressions in the template itself.

Run directly, or via the stdin-exec wrapper the other *_qgis tests use:
    "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" tests/test_label_priority_ladder_qgis.py
"""
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

from qgis.core import (Qgis, QgsApplication, QgsRuleBasedLabeling,  # noqa: E402
                       QgsVectorLayer)

TEMPLATE = os.path.join(REPO_ROOT, "Template", "LGS_MappingTemplate.gpkg")

OBSTACLE_FACTOR = 2.0

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


def load(name):
    layer = QgsVectorLayer("%s|layername=%s" % (TEMPLATE, name), name, "ogr")
    if not check(layer.isValid(), "%s loads" % name):
        return None
    layer.loadDefaultStyle()
    return layer


def main():
    if not os.path.exists(TEMPLATE):
        print("SKIP: template not found: " + TEMPLATE)
        return 0

    # FieldNotebook: rule ladder + obstacle factors
    fn = load("1 - FieldNotebook")
    if fn is not None and check(
            isinstance(fn.labeling(), QgsRuleBasedLabeling),
            "FieldNotebook labeling is rule-based"):
        rules = {r.description(): r.settings()
                 for r in fn.labeling().rootRule().children()}
        ladder = {
            "Dip Labels": (10, Qgis.LabelOverlapHandling.AllowOverlapAtNoCost),
            "SymbolSuffix Labels": (8, Qgis.LabelOverlapHandling.PreventOverlap),
            "Fallback Labels (Comments/Labels)":
                (3, Qgis.LabelOverlapHandling.AllowOverlapIfRequired),
            "Regolith Note":
                (2, Qgis.LabelOverlapHandling.AllowOverlapIfRequired),
        }
        for desc, (priority, overlap) in ladder.items():
            if not check(desc in rules, "rule %r present" % desc):
                continue
            s = rules[desc]
            check(s.priority == priority,
                  "%s priority %s, want %s" % (desc, s.priority, priority))
            check(s.placementSettings().overlapHandling() == overlap,
                  "%s overlap %s, want %s"
                  % (desc, s.placementSettings().overlapHandling(), overlap))
            check(round(s.obstacleSettings().factor(), 4) == OBSTACLE_FACTOR,
                  "%s obstacleFactor %s, want %s"
                  % (desc, s.obstacleSettings().factor(), OBSTACLE_FACTOR))

    # Linework: never hides an annotation, stays at ladder rung 5
    lw = load("2 - Linework")
    if lw is not None and check(lw.labeling() is not None, "Linework labeled"):
        s = lw.labeling().settings()
        check(s.priority == 5, "Linework priority %s, want 5" % s.priority)
        check(s.placementSettings().overlapHandling()
              == Qgis.LabelOverlapHandling.AllowOverlapIfRequired,
              "Linework overlap %s, want AllowOverlapIfRequired"
              % s.placementSettings().overlapHandling())

    # Overlay: rung 4
    ov = load("3 - Overlay")
    if ov is not None and check(ov.labeling() is not None, "Overlay labeled"):
        s = ov.labeling().settings()
        check(s.priority == 4, "Overlay priority %s, want 4" % s.priority)
        check(s.placementSettings().overlapHandling()
              == Qgis.LabelOverlapHandling.AllowOverlapIfRequired,
              "Overlay overlap %s, want AllowOverlapIfRequired"
              % s.placementSettings().overlapHandling())

    # Basemap: mobile, short-leadered, cost-paying, non-obstacle, rung 6
    bm = load("4 - Basemap")
    if bm is not None and check(bm.labeling() is not None, "Basemap labeled"):
        s = bm.labeling().settings()
        check(s.priority == 6, "Basemap priority %s, want 6" % s.priority)
        check(s.placementSettings().overlapHandling()
              == Qgis.LabelOverlapHandling.AllowOverlapIfRequired,
              "Basemap overlap %s, want AllowOverlapIfRequired"
              % s.placementSettings().overlapHandling())
        check(s.placement == Qgis.LabelPlacement.Horizontal,
              "Basemap placement %s, want Horizontal" % s.placement)
        check(int(s.polygonPlacementFlags()) == 3,
              "Basemap polygonPlacementFlags %s, want 3 (inside preferred + outside)"
              % int(s.polygonPlacementFlags()))
        check(bool(s.fitInPolygonOnly),
              "Basemap fitInPolygonOnly off - outside placement would be unbounded")
        check(round(s.dist, 4) == 18.75,
              "Basemap dist %s, want 18.75 (0.5 x U - short leaders)" % s.dist)
        check(round(s.pointSettings().maximumDistance(), 4) == 93.75,
              "Basemap maximumDistance %s, want 93.75"
              % s.pointSettings().maximumDistance())
        callout = s.callout()
        check(callout is not None and callout.enabled(),
              "Basemap callout enabled")
        if callout is not None:
            check(callout.type() == "simple",
                  "Basemap callout type %r, want 'simple' - manhattan's "
                  "right-angle elbow reads badly" % callout.type())
            check(round(callout.minimumLength(), 4) == 1.0,
                  "Basemap callout minLength %s, want 1 MM (no stubs inside)"
                  % callout.minimumLength())
        check(not s.obstacleSettings().isObstacle(),
              "Basemap fills registered as obstacles - uniform cost noise")

    print("%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    if QgsApplication.instance() is None:
        QgsApplication.setPrefixPath(
            os.environ.get("QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
        _app = QgsApplication([], False)
        _app.initQgis()
    sys.exit(main())
