"""
Project terrain configuration for QField 3D.

QField 4.1+'s 3D map view reads the project's elevation-properties
terrain provider. This module owns setting it and choosing which DEM it
points at; the QField exporter's terrain selector is the UI on top of it.

The provider's scale stays 1.0 in the live project: baking exaggeration
into it would skew elevation-profile readings. The QField z-factor is
injected only into the exported project copy
(qfield_export/core/terrain_xml.py).
"""

from qgis.core import QgsProject, QgsRasterDemTerrainProvider

try:
    from . import detect
    from ..z_filter.auto_layers import detect_raster_layers
    from ..z_filter.expression import SCOPE, ENTRY_RASTERS, parse_rasters
except ImportError:  # loaded outside the plugin package
    from view3d import detect
    from z_filter.auto_layers import detect_raster_layers
    from z_filter.expression import SCOPE, ENTRY_RASTERS, parse_rasters

# Historical key name — the desktop 3D view that coined it is gone, but
# existing projects carry their pinned DEM under it. Never rename.
ENTRY_DEM_LAYER = "view3d/demLayerId"
ROLE_PROPERTY = "lgs/dem_role"


# ------------------------------------------------------------ DEM choice

def dem_rows(project=None):
    """Plain rows for detect.choose_dem, plus the layer under 'layer'."""
    project = project or QgsProject.instance()
    tied_ids = set()
    raw, _ = project.readEntry(SCOPE, ENTRY_RASTERS, "")
    for entry in parse_rasters(raw):
        if entry.get('id'):
            tied_ids.add(entry['id'])
    rows = []
    for item in detect_raster_layers(project):
        layer = item['layer']
        try:
            bands = layer.bandCount()
        except Exception:
            bands = 1
        rows.append({
            'id': layer.id(),
            'name': layer.name(),
            'role': layer.customProperty(ROLE_PROPERTY, '') or '',
            'tied': layer.id() in tied_ids,
            'bands': bands,
            'layer': layer,
        })
    return rows


def choose_dem_layer(project=None):
    """(QgsRasterLayer or None, reason) — see detect.choose_dem."""
    project = project or QgsProject.instance()
    row, reason = detect.choose_dem(dem_rows(project), pinned_dem_id(project))
    return (row['layer'] if row else None), reason


def pinned_dem_id(project=None):
    project = project or QgsProject.instance()
    value, _ = project.readEntry(SCOPE, ENTRY_DEM_LAYER, "")
    return value or None


def pin_dem_layer(layer, project=None):
    """Persist an explicit user pick; stamping the role makes the choice
    survive save/reload of the layer id and travel with pit DEMs."""
    project = project or QgsProject.instance()
    project.writeEntry(SCOPE, ENTRY_DEM_LAYER, layer.id())
    project.setDirty(True)


# ------------------------------------------------------ terrain provider

def ensure_project_terrain(dem_layer, project=None):
    """Point the project's terrain provider at dem_layer (scale/offset
    stay 0/1 — see module docstring). No-op when already set."""
    project = project or QgsProject.instance()
    current = current_terrain_layer(project)
    if current is not None and current.id() == dem_layer.id():
        return False
    provider = QgsRasterDemTerrainProvider()
    provider.setLayer(dem_layer)
    provider.setScale(1.0)
    provider.setOffset(0.0)
    project.elevationProperties().setTerrainProvider(provider)
    project.setDirty(True)
    return True


def current_terrain_layer(project=None):
    """The raster behind the project terrain provider, or None."""
    project = project or QgsProject.instance()
    provider = project.elevationProperties().terrainProvider()
    if provider is None or provider.type() != 'raster':
        return None
    layer = provider.layer()
    return layer if layer is not None and layer.isValid() else None
