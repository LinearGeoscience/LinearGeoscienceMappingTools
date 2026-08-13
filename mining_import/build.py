"""
IR -> QgsFeature.

Everything format-specific has already been resolved by the reader, so this
module only decides how the neutral IR lands in the target schema: which
attrs become columns, which are JSON-encoded into Attributes, and how Z is
carried.

Runs on the import worker thread — it builds features and geometry only, and
never touches project layers, iface or widgets.
"""

import json

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsLineString,
    QgsPoint,
    QgsPointXY,
)

try:
    from . import schema
    from .ir import polyline_length_3d, z_range
except ImportError:  # non-package execution inside QGIS
    import schema
    from ir import polyline_length_3d, z_range


def _column_names(layer_name):
    return {name for name, _type in schema.field_defs(layer_name)}


def _split_attrs(attrs, layer_name):
    """Partition attrs into real columns and the Attributes JSON remainder."""
    columns = _column_names(layer_name)
    mapped = {}
    extra = {}
    for key, value in (attrs or {}).items():
        if key in columns:
            mapped[key] = value
        else:
            extra[key] = value
    return mapped, extra


def make_feature(fields, geometry, attrs):
    """Feature with attributes set by name.

    By name, not by index, so it survives a target whose field order differs
    -- an existing GeoPackage layer has a leading fid that shifts every
    positional index by one.
    """
    feat = QgsFeature(fields)
    feat.setGeometry(geometry)
    for name, value in attrs.items():
        idx = fields.lookupField(name)
        if idx >= 0:
            feat.setAttribute(idx, value)
    return feat


def _base_attrs(layer_name, item_attrs, provenance):
    mapped, extra = _split_attrs(item_attrs, layer_name)
    attrs = dict(provenance)
    attrs.update(mapped)
    if extra:
        attrs['Attributes'] = json.dumps(extra, sort_keys=True,
                                         separators=(',', ':'),
                                         default=str)
    return attrs


def _z_or_zero(point):
    z = point[2] if len(point) > 2 else None
    return 0.0 if z is None else z


def build_polylines(parsed, provenance, fields):
    """LineStringZ features, one per polyline with at least 2 points.

    Returns (features, degenerate) where degenerate counts polylines that
    could not form a line. With the Surpac reader routing single points to
    stations this should be zero, but a format that emits a 1-point polyline
    directly must not crash the import.
    """
    features = []
    degenerate = 0
    for poly in parsed.polylines:
        points = poly.points
        if len(points) < 2:
            degenerate += 1
            continue
        zmin, zmax = z_range(points)
        geom = QgsGeometry(QgsLineString(
            [QgsPoint(p[0], p[1], _z_or_zero(p)) for p in points]))
        attrs = _base_attrs(schema.STRINGS_LAYER, poly.attrs, provenance)
        # Z_Min/Z_Max stay NULL when no point carried an elevation, so the Z
        # Filter's range clause never matches instead of pinning the feature
        # to sea level.
        attrs['Z_Min'] = zmin
        attrs['Z_Max'] = zmax
        attrs.setdefault('PointCount', len(points))
        attrs['Closed'] = bool(poly.closed)
        attrs['Length3D'] = polyline_length_3d(points)
        features.append(make_feature(fields, geom, attrs))
    return features, degenerate


def build_stations(parsed, provenance, fields):
    features = []
    for station in parsed.stations:
        point = station.point
        z = point[2] if len(point) > 2 else None
        geom = QgsGeometry(QgsPoint(point[0], point[1], _z_or_zero(point)))
        attrs = _base_attrs(schema.STATIONS_LAYER, station.attrs, provenance)
        # A point is a single elevation, not a range: populate both so the Z
        # Filter can use either mode, but Elevation is the meaningful one.
        attrs['Elevation'] = z
        attrs['Z_Min'] = z
        attrs['Z_Max'] = z
        features.append(make_feature(fields, geom, attrs))
    return features


def build_annotations(parsed, provenance, fields):
    features = []
    for note in parsed.annotations:
        point = note.point
        z = point[2] if len(point) > 2 else None
        geom = QgsGeometry(QgsPoint(point[0], point[1], _z_or_zero(point)))
        attrs = _base_attrs(schema.TEXT_LAYER, note.attrs, provenance)
        attrs['Text'] = note.text
        attrs['Elevation'] = z
        attrs['Z_Min'] = z
        attrs['Z_Max'] = z
        features.append(make_feature(fields, geom, attrs))
    return features


def build_outlines(parsed, provenance, fields, warnings):
    """Dissolve each surface's triangles into one 2D (multi)polygon footprint.

    Z is carried by Z_Min/Z_Max rather than the geometry, matching the
    range-mode convention for polygons.
    """
    features = []
    for surface in parsed.surfaces:
        vertices = surface.vertices
        tri_geoms = []
        bad = 0
        for tri in surface.triangles:
            try:
                ring = [QgsPointXY(vertices[v][0], vertices[v][1])
                        for v in tri]
            except IndexError:
                bad += 1
                continue
            ring.append(ring[0])
            tri_geoms.append(QgsGeometry.fromPolygonXY([ring]))
        if bad:
            warnings.append('{0}: {1} triangle(s) referenced missing points '
                            'and were skipped'.format(parsed.name, bad))
        if not tri_geoms:
            warnings.append('{0}: no usable triangles — outline '
                            'skipped'.format(parsed.name))
            continue

        geom = QgsGeometry.unaryUnion(tri_geoms)
        if geom.isEmpty() or not geom.isGeosValid():
            geom = geom.makeValid()
        if geom.isEmpty() or not geom.isGeosValid():
            geom = geom.buffer(0, 5)
        if geom.isEmpty():
            warnings.append('{0}: outline union came back empty — outline '
                            'skipped'.format(parsed.name))
            continue
        geom.convertToMultiType()

        zmin, zmax = z_range(vertices)
        attrs = _base_attrs(schema.OUTLINES_LAYER, surface.attrs, provenance)
        attrs['Z_Min'] = zmin
        attrs['Z_Max'] = zmax
        attrs.setdefault('TriangleCount', len(surface.triangles))
        attrs['Area2D'] = geom.area()
        features.append(make_feature(fields, geom, attrs))
    return features
