#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
One-off template updater: add the "Elevation" (double) field to the four
standard layers in Template/LGS_MappingTemplate.gpkg.

Idempotent — layers that already have the field are skipped.

Run inside the QGIS Python console, or headlessly from an OSGeo4W shell:
    python-qgis add_elevation_to_template.py [path\\to\\template.gpkg]
"""

import os
import sys

try:
    from qgis.core import QgsApplication, QgsVectorLayer, QgsField
    from qgis.PyQt.QtCore import QMetaType
except ImportError:
    sys.exit("Must be run with QGIS python (python-qgis / QGIS console).")

LGS_LAYERS = ['1 - FieldNotebook', '2 - Overlay', '3 - Linework', '4 - Basemap']
ELEVATION_FIELD = "Elevation"


def add_elevation(template_path):
    if not os.path.exists(template_path):
        raise SystemExit(f"Template not found: {template_path}")
    results = []
    for name in LGS_LAYERS:
        layer = QgsVectorLayer(f"{template_path}|layername={name}", name, "ogr")
        if not layer.isValid():
            results.append((name, "MISSING LAYER"))
            continue
        if layer.fields().indexOf(ELEVATION_FIELD) != -1:
            results.append((name, "already present"))
            continue
        ok = layer.dataProvider().addAttributes(
            [QgsField(ELEVATION_FIELD, QMetaType.Type.Double)])
        layer.updateFields()
        results.append((name, "added" if ok else "FAILED"))
    return results


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    template = sys.argv[1] if len(sys.argv) > 1 else default

    standalone = QgsApplication.instance() is None
    app = None
    if standalone:
        app = QgsApplication([], False)
        app.initQgis()
    try:
        for name, status in add_elevation(template):
            print(f"  {name}: {status}")
    finally:
        if app is not None:
            app.exitQgis()


if __name__ == "__main__":
    main()
