"""
Terrain-provider XML injection for exported QField projects.

QField 4.1+'s 3D map view reads the project's <ElevationProperties>
terrain provider — including its scale (vertical exaggeration) and
offset — and falls back to online Mapzen tiles only when the terrain is
flat and unscaled. Baking a raster provider pointing at the bundled DEM
is what makes offline, pit-scale 3D work in the field.

This is XML injection rather than the QGIS API on purpose: the export
copies the ON-DISK project file, so in-memory elevation properties never
reach the export — and injection lets the exported copy carry scale != 1
while the live project's provider stays at true scale.

Pure stdlib (ElementTree) so it unit-tests headless.
"""

ELEVATION_TAG = "ElevationProperties"
PROVIDER_TAG = "terrainProvider"
# The inner element name QgsRasterDemTerrainProvider actually writes and
# reads. QGIS's schema is NESTED:
#   <ElevationProperties>
#     <terrainProvider type="raster">
#       <TerrainProvider layer=".." offset=".." scale=".." .../>
#     </terrainProvider>
#   </ElevationProperties>
# Putting the attributes flat on <terrainProvider> parses as an empty
# provider and QField silently shows FLAT terrain - proven against
# QgsProject.write() output on 3.40.9.
INNER_TAG = "TerrainProvider"


def inject_terrain(root, dem_layer_id, dem_source, dem_layer_name="",
                   dem_provider="gdal", scale=1.0, offset=0.0):
    """Replace-or-add the terrain provider on a parsed .qgs root.

    root: the <qgis> Element of the exported project file.
    dem_source: the DEM path as the exported project references it
        (relative, e.g. './pit_dem.tif').
    Returns the new <ElevationProperties> element. Idempotent by
    construction: any existing ElevationProperties is removed first.
    """
    import xml.etree.ElementTree as ET

    for existing in root.findall(ELEVATION_TAG):
        root.remove(existing)

    elem = ET.SubElement(root, ELEVATION_TAG)
    provider = ET.SubElement(elem, PROVIDER_TAG)
    provider.set("type", "raster")
    inner = ET.SubElement(provider, INNER_TAG)
    inner.set("offset", _num(offset))
    inner.set("scale", _num(scale))
    inner.set("layer", dem_layer_id or "")
    inner.set("layerName", dem_layer_name or "")
    inner.set("layerSource", dem_source or "")
    inner.set("layerProvider", dem_provider)
    return elem


def _num(value):
    """Attribute-friendly number: '1' not '1.0', '1.5' stays '1.5'."""
    value = float(value)
    if value == int(value):
        return str(int(value))
    return repr(value)
