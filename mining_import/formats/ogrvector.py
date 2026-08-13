"""
OGR-backed reader for ESRI Shapefile and GeoPackage sources.

Survey departments increasingly hand over GIS-native exports rather than
Surpac or DXF: a shapefile of development strings merged per level, or a
GeoPackage of pickup points. Geometry type is the routing signal — points
become stations, lines become strings, polygon rings become closed strings —
and the same layer-name tokens the DXF reader trusts ('pegs', 'stn') still
route a lines layer of survey pickups to stations.

The osgeo import is deliberately inside the functions that need it: this
module must load without GDAL's python bindings (tests/test_mining_purity.py
loads every module under formats/ standalone), and both sniffers stay
stdlib-only so a folder scan never pays an OGR startup cost.

A multi-layer GeoPackage folds into ONE ParsedFile — the merge engine keys on
the source file (ir.py's one-ParsedFile-per-file invariant), exactly as the
DXF reader folds many CAD layers into one file. Layer identity survives in
SrcLayer.

Attribute fields are mapped to schema columns through a whitelist of aliases.
The whitelist is also the guard: a source column named SourceKey, BatchId or
SourceFile (common when the source was itself exported from GIS — including
from this importer's own output) must never override the provenance columns
the merge engine depends on, so any reserved-but-unmapped field name is
lowercased before it lands in the Attributes JSON.
"""

import os
import sqlite3
import struct
import urllib.parse

try:  # package context
    from ..ir import (ParsedFile, Polyline, Station, is_closed, merge_attrs)
except ImportError:  # loaded directly by path
    from ir import (ParsedFile, Polyline, Station, is_closed, merge_attrs)

try:  # sibling reader: reuse its layer-name routing tokens
    from .dxf import apply_layer_rules
except ImportError:
    from dxf import apply_layer_rules

# Registry keys by extension; read_file derives its format_key from the path
# so both registry entries can share this one module.
FORMAT_KEYS = {'.shp': 'shapefile', '.gpkg': 'geopackage'}

# The import log table this importer writes into its output GeoPackage.
# Hardcoded (with schema.LOG_TABLE as the source of truth) because schema.py
# imports qgis and this module must not.
_OWN_LOG_TABLE = 'lgs_mining_import_log'

_SHP_MAGIC = 9994  # big-endian int32 at byte 0 of every .shp
_SQLITE_HEADER = b'SQLite format 3\x00'
_GPKG_APP_IDS = (b'GPKG', b'GP10', b'GP11')

# Source field name (lowercased) -> schema column. Only these ever become
# real columns; everything else goes to the Attributes JSON.
_FIELD_ALIASES = {
    'pointid': 'PointId', 'point_id': 'PointId', 'ptid': 'PointId',
    'pt_id': 'PointId', 'name': 'PointId', 'id': 'PointId',
    'station': 'PointId', 'station_id': 'PointId',
    'code': 'Code', 'desc': 'Code', 'description': 'Code',
    'stringno': 'StringNo', 'string_no': 'StringNo',
    'level': 'Level', 'lvl': 'Level',
    'elevation': 'Elevation', 'elev': 'Elevation', 'rl': 'Elevation',
    'z': 'Elevation',
    'surveydate': 'SurveyDate', 'survey_date': 'SurveyDate',
    'surveyor': 'Surveyor',
    'bearing': 'Bearing', 'domain': 'Domain', 'setupcode': 'SetupCode',
    'surveytype': 'SurveyType', 'survey_type': 'SurveyType',
    'instrument': 'Instrument', 'instrserial': 'InstrSerial',
    'jobcode': 'JobCode',
    'srclayer': 'SrcLayer',
}

# GIS bookkeeping columns that carry no survey information.
_DROP_FIELDS = {'fid', 'ogc_fid', 'objectid', 'shape_length', 'shape_leng',
                'shape_area'}

# Schema columns the importer itself computes or stamps. A source field with
# one of these exact names would override them inside build._base_attrs, so
# it is renamed (lowercased) into the Attributes JSON instead.
_RESERVED_COLUMNS = {
    'SourceKey', 'SourceFile', 'Format', 'BatchId', 'ImportedAt',
    'Z_Min', 'Z_Max', 'SectionIndex', 'SectionCount', 'PointCount',
    'Length3D', 'Closed', 'Attributes', 'Elevation',
}


def sniff_shp(path):
    """Confidence that path is a real shapefile: the 9994 magic number."""
    try:
        with open(path, 'rb') as fh:
            head = fh.read(4)
    except OSError:
        return 0.0
    if len(head) == 4 and struct.unpack('>i', head)[0] == _SHP_MAGIC:
        return 0.9
    return 0.0


def sniff_gpkg(path):
    """Confidence that path is a GeoPackage worth importing.

    Returns 0.0 for a GeoPackage containing this importer's own log table:
    that file IS this tool's output (or a backup copy of it), and re-ingesting
    it would loop the importer's product back in as a source. The registry
    entry's min_confidence floor (0.2) is what turns that 0.0 into "not
    claimed" — see the comment on the FormatSpec.
    """
    try:
        with open(path, 'rb') as fh:
            head = fh.read(72)
    except OSError:
        return 0.0
    if len(head) < 72 or not head.startswith(_SQLITE_HEADER):
        return 0.0
    if head[68:72] not in _GPKG_APP_IDS:
        # SQLite but not declaring itself a GeoPackage; too odd to claim.
        return 0.1
    try:
        if _has_own_log_table(path):
            return 0.0
    except sqlite3.Error:
        # Unreadable (locked, corrupt): stay below the 0.2 floor rather
        # than claiming a file we could not rule out as our own output.
        return 0.15
    return 0.9


def _has_own_log_table(path):
    uri = 'file:{0}?mode=ro'.format(
        urllib.parse.quote(os.path.abspath(path).replace('\\', '/')))
    con = sqlite3.connect(uri, uri=True)
    try:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (_OWN_LOG_TABLE,)).fetchone()
        return row is not None
    finally:
        con.close()


def _map_fields(defn):
    """(index -> schema column, index -> Attributes key) for a layer defn.

    Reserved provenance/computed columns are lowercased on their way to the
    Attributes JSON so they can never shadow the importer's own values.
    """
    mapped = {}
    extra = {}
    for i in range(defn.GetFieldCount()):
        fname = defn.GetFieldDefn(i).GetName()
        lowered = fname.lower()
        if lowered in _DROP_FIELDS:
            continue
        target = _FIELD_ALIASES.get(lowered)
        if target is not None:
            mapped[i] = target
        elif fname in _RESERVED_COLUMNS:
            extra[i] = lowered
        else:
            extra[i] = fname
    return mapped, extra


def _feature_attrs(feature, mapped, extra):
    """One feature's attrs dict, ready for merge_attrs."""
    attrs = {}
    for index, key in mapped.items():
        if feature.IsFieldSetAndNotNull(index):
            attrs[key] = feature.GetField(index)
    for index, key in extra.items():
        if feature.IsFieldSetAndNotNull(index):
            attrs[key] = feature.GetField(index)
    return attrs


def _elevation_of(attrs):
    value = attrs.get('Elevation')
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _line_points(geom, fallback_z):
    is3d = bool(geom.Is3D())
    points = []
    for i in range(geom.GetPointCount()):
        z = geom.GetZ(i) if is3d else fallback_z
        points.append((geom.GetX(i), geom.GetY(i), z))
    return points


class _LayerCollector(object):
    """Routes one layer's features into IR, honouring kind overrides."""

    def __init__(self, ogr, kind_override):
        self.ogr = ogr
        self.kind = kind_override  # 'stations', 'strings' or None
        self.polylines = []
        self.stations = []
        self.skipped_geoms = 0

    def add(self, geom, attrs):
        ogr = self.ogr
        flat = ogr.GT_Flatten(geom.GetGeometryType())
        if flat == ogr.wkbPoint:
            z = geom.GetZ(0) if geom.Is3D() else _elevation_of(attrs)
            self.stations.append(
                Station((geom.GetX(0), geom.GetY(0), z), dict(attrs)))
        elif flat == ogr.wkbLineString:
            points = _line_points(geom, _elevation_of(attrs))
            self._add_line(points, attrs, closed=is_closed(points))
        elif flat == ogr.wkbPolygon:
            fallback_z = _elevation_of(attrs)
            for i in range(geom.GetGeometryCount()):
                points = _line_points(geom.GetGeometryRef(i), fallback_z)
                self._add_line(points, attrs, closed=True)
        elif flat in (ogr.wkbMultiPoint, ogr.wkbMultiLineString,
                      ogr.wkbMultiPolygon, ogr.wkbGeometryCollection):
            for i in range(geom.GetGeometryCount()):
                self.add(geom.GetGeometryRef(i), attrs)
        else:
            self.skipped_geoms += 1

    def _add_line(self, points, attrs, closed):
        if not points:
            return
        if len(points) < 2 or self.kind == 'stations':
            # A pegs layer holds pegs even when the exporter drew them as
            # tiny lines — same reading as the DXF reader's _add_line.
            for point in points:
                self.stations.append(Station(point, dict(attrs)))
            return
        self.polylines.append(
            Polyline(points=list(points), attrs=dict(attrs), closed=closed))


def read_file(path, companions=None, level=None, kind=None,
              progress_cb=None, **_options):
    """Read every vector layer of a shapefile or GeoPackage into one
    ParsedFile.

    kind: the dialog's "Import as" override. 'stations' flattens every
    geometry to its vertices; 'strings' switches off the layer-name token
    routing (points stay points — they cannot become a line one at a time).
    None lets geometry type and layer name decide.
    companions: accepted for the shapefile sidecars but unused — OGR opens
    .dbf/.shx/.prj beside the .shp itself.
    """
    from osgeo import ogr  # lazy: see module docstring

    name = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    format_key = FORMAT_KEYS.get(ext, 'geopackage')

    polylines = []
    stations = []
    warnings = []
    layer_counts = {}
    skipped_layers = []
    skipped_geoms = 0

    ds = None
    try:
        try:
            ds = ogr.Open(path, 0)
        except Exception as exc:  # GDAL may be in exceptions mode
            raise RuntimeError('{0}: OGR could not open the file '
                               '({1})'.format(name, exc))
        if ds is None:
            raise RuntimeError('{0}: OGR could not open the file'.format(name))

        layer_count = ds.GetLayerCount()
        for li in range(layer_count):
            layer = ds.GetLayerByIndex(li)
            layer_name = layer.GetName()
            if layer.GetGeomType() == ogr.wkbNone:
                skipped_layers.append(layer_name)
                continue

            token_kind, layer_level = apply_layer_rules(layer_name)
            if token_kind == 'text':
                token_kind = None  # vector features carry no drawn text
            effective_kind = kind if kind else token_kind
            if kind == 'strings':
                effective_kind = None

            base = {'SrcLayer': layer_name}
            if layer_level:
                base['Level'] = layer_level

            srs = layer.GetSpatialRef()
            if srs is not None and srs.IsGeographic():
                warnings.append(
                    '{0}: layer "{1}" declares a geographic CRS (lat/lon '
                    'degrees) — coordinates are imported as-is; check the '
                    'import CRS matches.'.format(name, layer_name))

            defn = layer.GetLayerDefn()
            mapped, extra = _map_fields(defn)
            collector = _LayerCollector(
                ogr, 'stations' if effective_kind == 'stations' else None)

            count = 0
            layer.ResetReading()
            for feature in layer:
                geom = feature.GetGeometryRef()
                if geom is None or geom.IsEmpty():
                    continue
                attrs = merge_attrs(base, _feature_attrs(
                    feature, mapped, extra))
                collector.add(geom, attrs)
                count += 1

            layer_counts[layer_name] = count
            polylines.extend(collector.polylines)
            stations.extend(collector.stations)
            skipped_geoms += collector.skipped_geoms
    finally:
        ds = None  # release NOW: GDAL holds Windows file locks until closed

    if skipped_geoms:
        warnings.append('{0}: {1} feature part(s) had an unsupported '
                        'geometry type and were skipped'.format(
                            name, skipped_geoms))
    if not (polylines or stations):
        warnings.append('{0}: no drawable features found'.format(name))

    if level is not None:
        # Fallback only: a Level from a field or the layer name keeps it.
        stamp = {'Level': level}
        polylines = [p._replace(attrs=merge_attrs(stamp, p.attrs))
                     for p in polylines]
        stations = [s._replace(attrs=merge_attrs(stamp, s.attrs))
                    for s in stations]

    return ParsedFile(
        path=path,
        name=name,
        format_key=format_key,
        polylines=tuple(polylines),
        stations=tuple(stations),
        attrs={'layers': dict(sorted(layer_counts.items())[:200]),
               'skipped_layers': skipped_layers[:50]},
        warnings=tuple(warnings),
    )
