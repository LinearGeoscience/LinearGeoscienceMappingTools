"""
Surpac string (.str) and triangulation (.dtm) reader.

Surpac .str layout (verified against real survey exports):

    line 1: header  "name,date,purpose,memo"
    line 2: axis record "0, y, x, z, y, x, z"   (skipped positionally)
    then point records:
        string_no, Y(northing), X(easting), Z, d1, d2, ...
    a record of "0, 0.000, 0.000, 0.000," closes the current segment;
    "0, 0.000, 0.000, 0.000, END" ends the file.

Coordinates are stored northing-first and are swapped here, so points leave
this module as (x, y, z) = (easting, northing, elevation).

The description fields trailing each point record carry, in order:
    d1 point id, d2 datetime, d3 surveyor, d4 instrument, d5 serial,
    d6 job code
Sites do vary — anything past d6, or a file with fewer fields, is kept
verbatim under a 'D<n>' key rather than dropped.

Surpac .dtm layout: header lines, then an OBJECT / TRISOLATION preamble,
then triangle records "tri_id, v1, v2, v3, n1, n2, n3" where v1..v3 are
1-based indices into the paired .str file's point records in file order
(real point records only — separators, axis record and header excluded).
Those indices are converted to 0-based here so the QGIS side never has to
know which format a surface came from.

Pure python — no qgis, and the IR is reached through the dual-import idiom
so this file can be loaded directly by path in tests.
"""

import os

try:  # package context
    from .. import dfields
    from ..ir import (ParsedFile, Polyline, Station, Surface, is_closed,
                      merge_attrs)
except ImportError:  # loaded directly by path
    import dfields
    from ir import (ParsedFile, Polyline, Station, Surface, is_closed,
                    merge_attrs)

FORMAT_KEY = 'surpac'

# d-field layouts live in mining_import/dfields.py: the CSV exports of this
# same data carry literal d1..d15 headers, so both readers need them and
# readers must not import each other.
PROFILE_STRING = dfields.PROFILE_STRING
PROFILE_STATION = dfields.PROFILE_STATION

# Filename / folder tokens that mark survey control rather than linework.
# Matched as SUBSTRINGS: real files are named 'mga_all_stations.str' and live
# in 'StationsGDA', neither of which starts with any of these.
_STATION_NAME_TOKENS = ('stn', 'station', 'pickup', 'peg', 'control')

# Share of a file's records that must look station-shaped before the file is
# classified as stations on content alone.
_STATION_CONTENT_SHARE = 0.8

KIND_STRINGS = 'strings'
KIND_STATIONS = 'stations'


def sniff(path):
    """Confidence 0..1 that path is a Surpac string file.

    Cheap and structural: the second line must be an axis record (leading 0
    with real coordinates) and at least one following line must parse as a
    point record. Used only to break extension ties, so a wrong answer costs
    a mis-routed file, not a crash.
    """
    try:
        with open(path, 'r', errors='replace') as fh:
            lines = [fh.readline() for _ in range(12)]
    except OSError:
        return 0.0
    if len(lines) < 3:
        return 0.0
    axis = [f.strip() for f in lines[1].split(',')]
    if len(axis) < 4:
        return 0.0
    try:
        if int(float(axis[0])) != 0:
            return 0.0
        [float(f) for f in axis[1:4]]
    except ValueError:
        return 0.0
    for line in lines[2:]:
        fields = [f.strip() for f in line.split(',')]
        if len(fields) < 4:
            continue
        try:
            int(float(fields[0]))
            [float(f) for f in fields[1:4]]
            return 0.9
        except ValueError:
            continue
    return 0.3


def name_suggests_stations(path):
    """True when the filename or its parent folder names survey control.

    Substring, not prefix: the real file is 'mga_all_stations.str' inside
    'StationsGDA'. A prefix test missed both and sent 102 stations down the
    linework path, where each separator-delimited group became one polyline
    joining every station on a level.
    """
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    folder = os.path.basename(os.path.dirname(os.path.abspath(path))).lower()
    return any(token in stem or token in folder
               for token in _STATION_NAME_TOKENS)


def detect_d_profile(d_field_counts):
    return dfields.detect_profile(d_field_counts)


def classify(path, segments, d_field_counts):
    """Decide whether a parsed .str holds linework or survey control.

    Returns (kind, reason) — reason is surfaced as the dialog's tooltip so the
    decision is inspectable rather than magic.

    Content is weighed before names: a file whose records are station-shaped
    is stations whatever it is called, which is the signal that would have
    caught mga_all_stations.str on its own.
    """
    profile = detect_d_profile(d_field_counts)
    if profile == PROFILE_STATION:
        return KIND_STATIONS, 'records carry survey-control fields'

    total = sum(len(points) for points, _attrs, _no in segments)
    if total:
        lone = sum(len(points) for points, _attrs, _no in segments
                   if len(points) < 2)
        if lone >= total * _STATION_CONTENT_SHARE:
            return KIND_STATIONS, 'file is almost entirely single points'

    if name_suggests_stations(path):
        return KIND_STATIONS, 'file or folder name says survey control'
    return KIND_STRINGS, 'multi-point strings'


def parse_d_fields(fields, profile=PROFILE_STRING):
    return dfields.parse(fields, profile)


def scan_str_lines(lines, name=''):
    """First pass: raw segments, before any d-field layout is assumed.

    Returns (segments, flat_points, dtm_index, d_field_counts, warnings) where
    segments is [(points, raw_d_field_lists, string_no)]. Splitting this out
    is what lets the profile and strings-vs-stations decision be made from the
    whole file rather than guessed per record.

    flat_points is every real point record in file order.

    dtm_index is the vertex space the paired .dtm's 1-based indices address,
    which is NOT the same list: Surpac counts the `0, 0.000, 0.000, 0.000,`
    SEPARATOR records as slots too. Those slots hold None here, and triangles
    referencing them are dropped.

    Verified against mga_mj_1238/1244: with separators counted, the summed
    triangle area matches the same surfaces exported as DXF polyface meshes
    exactly (2037.5 and 2353.0 m²); indexing real points only inflates them
    26-fold because every triangle then reaches across the mesh.

    Malformed records (fewer than 4 comma fields, non-numeric coordinates) are
    skipped and counted. A segment left open at EOF is flushed.
    """
    segments = []
    flat_points = []
    dtm_index = []
    d_field_counts = []
    warnings = []
    skipped_lines = 0

    current = []
    current_d = []
    current_string_no = None

    def close_segment():
        nonlocal current, current_d, current_string_no
        if current:
            segments.append((current, current_d, current_string_no))
        current = []
        current_d = []
        current_string_no = None

    for index, line in enumerate(lines):
        # Header and axis record are skipped positionally: the axis record
        # starts with 0 but carries real coordinates (in mga_all_stations.str
        # it is the local-grid origin transformed into MGA, not zeros), so it
        # must not be mistaken for a separator or for data.
        if index < 2:
            continue
        fields = [f.strip() for f in line.split(',')]
        if len(fields) < 4:
            if line.strip():
                skipped_lines += 1
            continue
        try:
            string_no = int(float(fields[0]))
        except ValueError:
            skipped_lines += 1
            continue
        if string_no == 0:
            if len(fields) > 4 and fields[4].upper() == 'END':
                break
            # A separator still consumes a slot in the .dtm's index space.
            dtm_index.append(None)
            close_segment()
            continue
        try:
            # Surpac stores northing first: swap to (x, y, z).
            point = (float(fields[2]), float(fields[1]), float(fields[3]))
        except ValueError:
            skipped_lines += 1
            continue
        # A change of string number ends the current string even without a
        # separator record. Files that rely on separators alone are
        # unaffected (their number is constant), but a file that switches
        # numbers mid-run would otherwise merge two strings into one.
        if current and string_no != current_string_no:
            close_segment()
        if not current:
            current_string_no = string_no
        raw = fields[4:]
        current.append(point)
        current_d.append(raw)
        flat_points.append(point)
        dtm_index.append(point)
        d_field_counts.append((len(raw), raw[3] if len(raw) > 3 else None))
    close_segment()

    if skipped_lines:
        warnings.append('{0}: {1} malformed record(s) skipped'.format(
            name or 'file', skipped_lines))
    return segments, flat_points, dtm_index, d_field_counts, warnings


def parse_str_lines(lines, name='', path=None, kind=None, profile=None):
    """Parse .str lines into (polylines, stations, flat_points, warnings, info).

    kind / profile override auto-detection (the dialog's "Import as" column).
    info carries the decisions made, for the dialog tooltip and the import log.
    """
    segments, flat_points, dtm_index, counts, warnings = scan_str_lines(
        lines, name=name)

    if profile is None:
        profile = detect_d_profile(counts)
    if kind is None:
        kind, reason = classify(path or name, segments, counts)
    else:
        reason = 'set by hand'

    polylines = []
    stations = []
    for points, raw_list, string_no in segments:
        attrs_list = [parse_d_fields(raw, profile) for raw in raw_list]
        if kind == KIND_STATIONS or len(points) < 2:
            # Survey stations, pegs and pickups. Each keeps ITS OWN metadata:
            # per-point detail genuinely varies here, unlike along a string.
            for point, attrs in zip(points, attrs_list):
                stations.append(Station(
                    point, merge_attrs({'StringNo': string_no}, attrs)))
            continue
        # For a drawn string the per-point metadata is near-identical along
        # the segment, so the first point's is representative. A documented
        # sample, not a promise.
        polylines.append(Polyline(
            points=points,
            attrs=merge_attrs(
                {'StringNo': string_no, 'PointCount': len(points)},
                attrs_list[0] if attrs_list else {}),
            closed=is_closed(points)))

    info = {'kind': kind, 'profile': profile, 'reason': reason,
            'dtm_index': dtm_index}
    return polylines, stations, flat_points, warnings, info


def parse_dtm_lines(lines):
    """Triangle vertex triples from .dtm lines, as ZERO-based indices.

    Surpac stores them 1-based; converting here means build.py never has to
    know the origin format. Neighbour fields are ignored. Only the first
    TRISOLATION block is read — Surpac drive solids ship one per level file.
    """
    triangles = []
    in_triangles = False
    for line in lines:
        stripped = line.strip()
        if not in_triangles:
            if stripped.upper().startswith('TRISOLATION'):
                in_triangles = True
            continue
        fields = [f.strip() for f in stripped.split(',')]
        if len(fields) < 4:
            break
        try:
            tri_id = int(float(fields[0]))
            if tri_id == 0:
                break
            triangles.append((int(float(fields[1])) - 1,
                              int(float(fields[2])) - 1,
                              int(float(fields[3])) - 1))
        except ValueError:
            break
    return triangles


def read_file(path, companions=None, level=None, kind=None, profile=None,
              **_options):
    """Read a .str (and its paired .dtm, if given) into one ParsedFile.

    companions: {'.dtm': path} as assembled by scan.discover().
    level: filename-derived label, used only where the records carry none.
    kind / profile: the dialog's "Import as" override; None means auto-detect.
    """
    name = os.path.basename(path)
    with open(path, 'r', errors='replace') as fh:
        lines = fh.readlines()

    header = lines[0].strip() if lines else ''
    polylines, stations, flat_points, warnings, info = parse_str_lines(
        lines, name=name, path=path, kind=kind, profile=profile)

    if level is not None:
        # FALLBACK, not an override: a station export carries the real level
        # per record in d3 (1182 … SURF) while the filename has none at all
        # ('mga_all_stations' would otherwise become the level for all 102
        # points). merge_attrs lets later dicts win, so the record's own
        # value must come second.
        stamp = {'Level': level}
        polylines = [p._replace(attrs=merge_attrs(stamp, p.attrs))
                     for p in polylines]
        stations = [s._replace(attrs=merge_attrs(stamp, s.attrs))
                    for s in stations]

    surfaces = []
    dtm_path = (companions or {}).get('.dtm')
    if dtm_path:
        with open(dtm_path, 'r', errors='replace') as fh:
            triangles = parse_dtm_lines(fh.readlines())
        index_space = info['dtm_index']
        if not triangles:
            warnings.append('{0}: no triangles found — surface skipped'.format(
                os.path.basename(dtm_path)))
        elif not flat_points:
            warnings.append('{0}: no points to triangulate — surface '
                            'skipped'.format(os.path.basename(dtm_path)))
        else:
            # Triangles index the space that COUNTS SEPARATORS (see
            # scan_str_lines); a triangle touching a separator slot is
            # meaningless and is dropped rather than drawn from (0,0,0).
            usable = [t for t in triangles
                      if all(0 <= v < len(index_space)
                             and index_space[v] is not None for v in t)]
            dropped = len(triangles) - len(usable)
            if dropped:
                warnings.append(
                    '{0}: {1} triangle(s) referenced missing points and were '
                    'skipped'.format(os.path.basename(dtm_path), dropped))
            if usable:
                # Compact to the vertices actually used, so the surface does
                # not carry a placeholder-riddled vertex list downstream.
                used = sorted({v for tri in usable for v in tri})
                remap = {old: new for new, old in enumerate(used)}
                vertices = [index_space[v] for v in used]
                compact = [(remap[a], remap[b], remap[c])
                           for a, b, c in usable]
                attrs = {'TriangleCount': len(compact)}
                if level is not None:
                    attrs['Level'] = level
                surfaces.append(Surface(vertices, compact, attrs))

    if not flat_points:
        warnings.append('{0}: no points found'.format(name))

    return ParsedFile(
        path=path,
        name=name,
        format_key=FORMAT_KEY,
        polylines=tuple(polylines),
        stations=tuple(stations),
        surfaces=tuple(surfaces),
        annotations=(),
        attrs={'header': header, 'kind': info['kind'],
               'profile': info['profile'], 'reason': info['reason']},
        warnings=tuple(warnings),
    )
