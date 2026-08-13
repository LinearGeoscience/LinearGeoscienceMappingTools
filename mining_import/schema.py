"""
Target GeoPackage schema: layer names, geometry types and field tables.

Layer names are chosen so the Z Filter panel auto-detects them with no
configuration (z_filter/detect.py NAME_HINTS contains 'string', 'station',
'level' and 'survey'), and the field names match its conventions:
  - Level    -> LABEL_FIELD_CANDIDATES[0], the display label
  - Z_Min/Z_Max -> RANGE_FIELD_PAIRS[0], range-mode filtering
  - Elevation   -> ELEVATION_FIELD_CANDIDATES[0], single-value mode, which is
                   the right mode for a point layer

Field types use QMetaType.Type.* (QGIS 3.38+ including 4.x); QVariant
overloads are removed in Qt6 and must not be used.
"""

from qgis.PyQt.QtCore import QMetaType
from qgis.core import QgsField, QgsFields, QgsWkbTypes

STRINGS_LAYER = 'MineStrings'
STATIONS_LAYER = 'MineStations'
OUTLINES_LAYER = 'MineLevelOutlines'
TEXT_LAYER = 'MineSurveyText'
LOG_TABLE = 'lgs_mining_import_log'

# The importer's OUTPUT revision, stamped into each import-log row. Bumped
# when a field is added (gpkg.py ALTERs an older file up) — and also when an
# import bug is fixed, because a source whose bytes are unchanged but whose
# last import produced wrong output must scan as "Changed" or the fix never
# reaches the data: the re-import that would heal it is exactly the one the
# fingerprint check skips.
#   2 — survey-control columns on MineStations (Domain/SetupCode/Bearing/
#       SurveyType), for the 15-d-field station export layout.
#   3 — no schema change: forces one re-import of sources written before the
#       station-routing fix (station files imported as level-spanning
#       polylines) and the .dtm separator-index fix (inflated outlines).
SCHEMA_VERSION = 3

_TEXT = QMetaType.Type.QString
_DOUBLE = QMetaType.Type.Double
_INT = QMetaType.Type.Int
_BOOL = QMetaType.Type.Bool

# Present on every spatial layer, in this order, so a feature built for one
# layer can be rebuilt against another without surprises.
_COMMON = (
    ('Level', _TEXT),
    ('Z_Min', _DOUBLE),
    ('Z_Max', _DOUBLE),
    ('SourceKey', _TEXT),
    ('SourceFile', _TEXT),
    ('Format', _TEXT),
    ('BatchId', _TEXT),
    ('ImportedAt', _TEXT),
    # Kept TEXT deliberately: source dates are unparseable in general
    # ('26.04.26 10:33:48') and a failed cast to QDateTime silently NULLs
    # real data. Normalised to ISO8601 only on a strict parse.
    ('SurveyDate', _TEXT),
    ('Surveyor', _TEXT),
    # Compact JSON of everything a format carries that has no column. Keeps a
    # DXF and a Datamine file compatible in one layer instead of exploding
    # the schema; the commonly-queried keys are promoted to real columns.
    ('Attributes', _TEXT),
)

_STRING_FIELDS = _COMMON + (
    ('StringNo', _INT),
    ('Code', _TEXT),
    ('SrcLayer', _TEXT),
    ('Closed', _BOOL),
    ('PointCount', _INT),
    ('Length3D', _DOUBLE),
)

_STATION_FIELDS = _COMMON + (
    # TEXT, not INT: Surpac ids are numeric but real station names are
    # alphanumeric ('MJ33', '1204RAW-01', 'MJ_PILLAR01', 'RAILWAY_NORT').
    ('PointId', _TEXT),
    ('Code', _TEXT),
    ('SrcLayer', _TEXT),
    ('Elevation', _DOUBLE),
    ('Instrument', _TEXT),
    ('InstrSerial', _TEXT),
    ('JobCode', _TEXT),
    # Survey-control export fields (schema v2). Everything a format carries
    # beyond these still reaches Attributes as JSON — LocalRL and ObsDate
    # live there rather than earning a column of their own.
    ('Domain', _TEXT),        # UG / SURF
    ('SetupCode', _TEXT),     # instrument setup or occupation code
    # TEXT: bearings are DDD.MMSS ('211.2907'), which is not a number —
    # storing it as a double would imply arithmetic that is wrong.
    ('Bearing', _TEXT),
    ('SurveyType', _TEXT),    # OPEN TRAVERSE / Baseline / Baseline Check
)

_OUTLINE_FIELDS = _COMMON + (
    ('SrcLayer', _TEXT),
    ('TriangleCount', _INT),
    ('Area2D', _DOUBLE),
)

_TEXT_FIELDS = _COMMON + (
    ('Text', _TEXT),
    ('Height', _DOUBLE),
    ('Rotation', _DOUBLE),
    ('SrcLayer', _TEXT),
    ('Elevation', _DOUBLE),
)

LAYERS = {
    STRINGS_LAYER: {
        'fields': _STRING_FIELDS,
        'wkb': QgsWkbTypes.Type.LineStringZ,
        'label': 'Strings',
    },
    STATIONS_LAYER: {
        'fields': _STATION_FIELDS,
        'wkb': QgsWkbTypes.Type.PointZ,
        'label': 'Stations',
    },
    OUTLINES_LAYER: {
        'fields': _OUTLINE_FIELDS,
        'wkb': QgsWkbTypes.Type.MultiPolygon,
        'label': 'Level outlines',
    },
    TEXT_LAYER: {
        'fields': _TEXT_FIELDS,
        'wkb': QgsWkbTypes.Type.PointZ,
        'label': 'Survey text',
    },
}

# Order matters only for progress reporting and the summary line.
LAYER_ORDER = (STRINGS_LAYER, STATIONS_LAYER, OUTLINES_LAYER, TEXT_LAYER)

# Layer name written by the pre-release Surpac-only build. Detected so the
# dialog can explain why an old GeoPackage looks half-empty, rather than
# silently writing a second set of layers beside it.
LEGACY_LAYERS = ('SurpacStrings', 'LevelOutlines')


def field_defs(layer_name):
    return LAYERS[layer_name]['fields']


def required_fields(layer_name):
    """Field names an existing layer must already have to be appended to."""
    return [name for name, _type in field_defs(layer_name)]


def wkb_type(layer_name):
    return LAYERS[layer_name]['wkb']


def make_fields(layer_name):
    fields = QgsFields()
    for name, mtype in field_defs(layer_name):
        fields.append(QgsField(name, mtype))
    return fields
