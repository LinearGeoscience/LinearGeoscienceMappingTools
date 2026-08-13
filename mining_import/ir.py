"""
Format-neutral intermediate representation for imported mining survey data.

Every reader in mining_import/formats/ turns a file on disk into exactly one
ParsedFile, whatever the source format. The QGIS side (build.py) only ever
sees this IR, so adding a format never touches the writer and adding a field
never touches a reader.

Pure python — imports nothing but the stdlib, so unit tests can load it
outside QGIS (see tests/pure_loader.py).

Conventions every reader must honour
------------------------------------
* Coordinates leave a reader as (x, y, z) = (easting, northing, elevation),
  already swapped out of whatever order the format stores them in.
* z may be None when the format carries no elevation. build.py writes such a
  vertex at Z=0.0 but leaves Z_Min/Z_Max NULL, so the Z Filter's range clause
  never matches it instead of pinning it to sea level. Never use NaN — OGR's
  handling of NaN doubles is not worth the risk.
* Surface.triangles are ZERO-based indices into Surface.vertices. Formats
  that store 1-based indices (Surpac .dtm) convert in the reader, so build.py
  never has to know where the surface came from.
* One ParsedFile per physical source file. A .str and its paired .dtm produce
  a single ParsedFile carrying both polylines and surfaces — the merge engine
  keys on a source file, so the mapping has to stay one-to-one.
* attrs dicts use target field names where one exists (Level, StringNo, Code,
  SurveyDate, Surveyor, SrcLayer, PointId, ...); anything else is free-form
  and gets JSON-encoded into the single Attributes column. That is what stops
  the schema exploding as formats are added.
"""

from collections import namedtuple

# A drawn string. points: [(x, y, z)], z may be None. attrs: dict describing
# the string as a whole — for formats that store per-point metadata this is
# sampled from the first point and is documented as a sample, not a promise.
Polyline = namedtuple('Polyline', 'points attrs closed', defaults=({}, False))

# A single surveyed point: station, peg, pickup, DXF POINT or block insert.
# attrs is THIS point's own metadata, never a neighbour's.
Station = namedtuple('Station', 'point attrs', defaults=({},))

# A triangulated surface. vertices: [(x, y, z)]; triangles: [(i, j, k)] with
# ZERO-based indices into vertices.
Surface = namedtuple('Surface', 'vertices triangles attrs', defaults=({},))

# A piece of text placed in space (DXF TEXT/MTEXT).
Annotation = namedtuple('Annotation', 'point text attrs', defaults=({},))

# One parsed source file.
#   path        absolute path as read
#   name        basename, used for human-facing messages
#   format_key  registry key of the reader that produced it ('surpac', ...)
#   attrs       file-level metadata (header line, DXF $INSUNITS, the CSV
#               dialect and mapping actually applied). Goes to the import
#               log's options_json — never onto features.
#   warnings    [str], merged into the run report by importer.py
ParsedFile = namedtuple(
    'ParsedFile',
    'path name format_key polylines stations surfaces annotations attrs '
    'warnings',
    defaults=((), (), (), (), {}, ()))


def z_range(points):
    """(min_z, max_z) over points, ignoring None elevations.

    Returns (None, None) when no point carries a usable elevation, which
    build.py writes as NULL Z_Min/Z_Max rather than inventing a range.
    """
    zs = [p[2] for p in points if len(p) > 2 and p[2] is not None]
    if not zs:
        return (None, None)
    return (min(zs), max(zs))


def merge_attrs(*dicts):
    """Shallow-merge attr dicts, later wins, skipping None values.

    Always returns a fresh dict — readers must never hand the same dict to
    two features, or editing one silently edits the other.
    """
    out = {}
    for d in dicts:
        if not d:
            continue
        for key, value in d.items():
            if value is not None:
                out[key] = value
    return out


def is_closed(points, tol=1e-6):
    """True when the first and last point coincide in x/y within tol.

    Z is deliberately ignored: a floor string that climbs a ramp back to its
    start is closed in plan, which is what 'closed' means to a surveyor.
    """
    if len(points) < 3:
        return False
    first, last = points[0], points[-1]
    return abs(first[0] - last[0]) <= tol and abs(first[1] - last[1]) <= tol


def polyline_length_3d(points):
    """Cumulative 3D length; falls back to 2D across segments missing Z."""
    total = 0.0
    for a, b in zip(points, points[1:]):
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        az = a[2] if len(a) > 2 else None
        bz = b[2] if len(b) > 2 else None
        dz = (bz - az) if (az is not None and bz is not None) else 0.0
        total += (dx * dx + dy * dy + dz * dz) ** 0.5
    return total
