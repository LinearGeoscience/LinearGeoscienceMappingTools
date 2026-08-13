"""
Delimited text reader: CSV / TXT / XYZ survey exports and pickup files.

Handles the two shapes that actually turn up:

* a plain point export — one station or pickup per row, with easting,
  northing and RL somewhere among the columns;
* a Surpac-style CSV twin of a .str, carrying literal `d1..d15` headers, which
  are mapped through the shared d-field profiles in mining_import/dfields.py.

Two deliberate refusals to guess:

* **String grouping is opt-in.** A `string` / `join` / `line` column pre-fills
  the mapping but never by itself turns rows into polylines. Real station
  exports carry a constant string number (99 in mga_all_stations.csv), and
  auto-grouping on it would chain every station in the file into one line —
  the exact failure this reader exists alongside a fix for.
* **Ambiguous easting/northing means ask.** guess_en_order returns None rather
  than picking, and the caller surfaces the mapping dialog.

Pure python — no qgis, and no imports of a sibling reader.
"""

import hashlib
import os

try:  # package context
    from .. import dfields
    from ..ir import ParsedFile, Polyline, Station, is_closed, merge_attrs
except ImportError:  # loaded directly by path
    import dfields
    from ir import ParsedFile, Polyline, Station, is_closed, merge_attrs

FORMAT_KEY = 'delimited'

COMMENT_PREFIXES = ('#', '//', '!')
CANDIDATE_DELIMITERS = (',', '\t', ';', '|')
_SAMPLE_LINES = 20

# Column-role aliases, most specific FIRST. An explicit name must outrank a
# bare initial: mga_all_stations.csv has both an `X` column and an `easting`
# column holding the same values, and 'easting' is the one that cannot be
# misread.
ROLE_X = 'x'
ROLE_Y = 'y'
ROLE_Z = 'z'
ROLE_ID = 'id'
ROLE_CODE = 'code'
ROLE_STRING = 'string'
ROLE_IGNORE = 'ignore'

ROLE_ALIASES = {
    ROLE_X: ('easting', 'east', 'xcoord', 'x_coord', 'xpt', 'e', 'x'),
    ROLE_Y: ('northing', 'north', 'ycoord', 'y_coord', 'ypt', 'n', 'y'),
    ROLE_Z: ('elevation', 'elev', 'height', 'zcoord', 'z_coord', 'zpt', 'rl',
             'z'),
    ROLE_ID: ('pointid', 'point_id', 'pointname', 'point', 'station', 'stn',
              'peg', 'name', 'id', 'pt', 'p'),
    ROLE_CODE: ('description', 'desc', 'code', 'feature', 'comment',
                'remarks', 'd'),
    ROLE_STRING: ('stringno', 'string_no', 'string', 'polyline', 'lineid',
                  'line', 'poly', 'group', 'join', 'seq', 'str'),
}

ROLE_LABELS = {
    ROLE_X: 'Easting (X)',
    ROLE_Y: 'Northing (Y)',
    ROLE_Z: 'Elevation (Z)',
    ROLE_ID: 'Point name / id',
    ROLE_CODE: 'Code / description',
    ROLE_STRING: 'String / join',
    ROLE_IGNORE: '—',
}

# Classic surveyor column orderings for headerless files.
PRESETS = {
    'PENZD': (ROLE_ID, ROLE_X, ROLE_Y, ROLE_Z, ROLE_CODE),
    'PNEZD': (ROLE_ID, ROLE_Y, ROLE_X, ROLE_Z, ROLE_CODE),
    'ENZD': (ROLE_X, ROLE_Y, ROLE_Z, ROLE_CODE),
    'NEZD': (ROLE_Y, ROLE_X, ROLE_Z, ROLE_CODE),
    'PNEZ': (ROLE_ID, ROLE_Y, ROLE_X, ROLE_Z),
    'XYZ': (ROLE_X, ROLE_Y, ROLE_Z),
    'XYZD': (ROLE_X, ROLE_Y, ROLE_Z, ROLE_CODE),
}

# Australian projected grids: northings run 6-8 million, eastings 100-900k.
# Only used to CONFIRM or to flag a swap, never to silently reorder.
_MIN_GRID_MAGNITUDE = 1e4
_EN_RATIO = 3.0


def _is_comment(line):
    stripped = line.lstrip()
    return any(stripped.startswith(p) for p in COMMENT_PREFIXES)


def _is_number(text):
    try:
        float((text or '').strip())
        return True
    except (TypeError, ValueError):
        return False


def read_lines(path, limit=None):
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as fh:
        if limit is None:
            return fh.read().splitlines()
        out = []
        for line in fh:
            out.append(line.rstrip('\r\n'))
            if len(out) >= limit:
                break
        return out


def detect_delimiter(lines):
    """The delimiter whose field count is highest AND constant across rows.

    Hand-rolled rather than csv.Sniffer, which is unreliable on numeric-only
    data — it happily reports '.' or a digit as the delimiter for a file of
    coordinates. Falls back to whitespace runs for classic .xyz files.
    """
    sample = [ln for ln in lines[:_SAMPLE_LINES]
              if ln.strip() and not _is_comment(ln)]
    if not sample:
        return ','
    best = None
    for delim in CANDIDATE_DELIMITERS:
        counts = [ln.count(delim) for ln in sample]
        if counts[0] < 1:
            continue
        if len(set(counts)) != 1:
            continue  # not constant -> not the delimiter
        if best is None or counts[0] > best[1]:
            best = (delim, counts[0])
    if best is not None:
        return best[0]
    whitespace = [len(ln.split()) for ln in sample]
    if len(set(whitespace)) == 1 and whitespace[0] > 1:
        return None  # None means "split on whitespace runs"
    return ','


def split_row(line, delimiter):
    if delimiter is None:
        return line.split()
    return [f.strip() for f in line.split(delimiter)]


def detect_header(rows):
    """True when row 0 names columns rather than holding data.

    Rule: at least half of row 0's fields fail float() while the same
    positions in row 1 parse. Handles `string,Y,X,Z,...` (all names) and
    refuses to call a numeric first row a header.
    """
    if len(rows) < 2:
        return False
    first, second = rows[0], rows[1]
    width = min(len(first), len(second))
    if not width:
        return False
    non_numeric = sum(1 for i in range(width) if not _is_number(first[i]))
    numeric_below = sum(1 for i in range(width) if _is_number(second[i]))
    return non_numeric >= width / 2.0 and numeric_below >= width / 2.0


def _alias_rank(name):
    """(role, rank) for a header name, or None. Lower rank = more specific."""
    lowered = (name or '').strip().lower().replace(' ', '').replace('-', '_')
    for role, aliases in ROLE_ALIASES.items():
        for rank, alias in enumerate(aliases):
            if lowered == alias:
                return role, rank
    return None


def detect_roles(header):
    """{role: column index} from header names.

    Where two columns claim a role, the more specific alias wins — so
    `easting` beats a bare `X`, which is what keeps the reversed duplicate
    pair in mga_all_stations.csv (cols 2/3 are N,E while cols 5/6 are E,N)
    from being resolved by luck.
    """
    best = {}
    for index, name in enumerate(header or ()):
        match = _alias_rank(name)
        if match is None:
            continue
        role, rank = match
        if role not in best or rank < best[role][0]:
            best[role] = (rank, index)
    return {role: index for role, (_rank, index) in best.items()}


def detect_d_columns(header):
    """Indices of a d1..dn header block, in order, or []."""
    found = {}
    for index, name in enumerate(header or ()):
        lowered = (name or '').strip().lower()
        if len(lowered) > 1 and lowered[0] == 'd' and lowered[1:].isdigit():
            found[int(lowered[1:])] = index
    if len(found) < 2 or 1 not in found:
        return []
    return [found[k] for k in sorted(found)]


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def guess_en_order(col_a, col_b):
    """('E','N') / ('N','E') / None for two numeric columns.

    Returns None — meaning ASK, never guess — whenever the magnitudes do not
    separate cleanly. Transposed easting/northing is the classic way to import
    a survey into the sea, so a coin flip is worse than a question.
    """
    a = [abs(v) for v in col_a if v is not None]
    b = [abs(v) for v in col_b if v is not None]
    if not a or not b:
        return None
    ma, mb = _median(a), _median(b)
    if ma < _MIN_GRID_MAGNITUDE or mb < _MIN_GRID_MAGNITUDE:
        return None
    if ma > mb * _EN_RATIO:
        return ('N', 'E')   # a is the northing
    if mb > ma * _EN_RATIO:
        return ('E', 'N')   # a is the easting
    return None


def signature(delimiter, has_header, header, width):
    """Stable id for 'a file shaped like this'.

    Keyed on header SHAPE, not filename: filenames vary per level, but a given
    total station's export layout does not — so a remembered mapping applies
    to every file from that source.
    """
    parts = [repr(delimiter), str(bool(has_header)), str(width)]
    parts.extend((h or '').strip().lower() for h in (header or ()))
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()


def inspect(path):
    """Everything the mapping dialog needs, without committing to anything.

    Returns a dict: delimiter, has_header, header, rows (sample), width,
    roles, d_columns, profile, signature, en_order, warnings.
    """
    raw = read_lines(path, limit=_SAMPLE_LINES * 3)
    # Comment lines are skipped only when present: mga_all_stations.csv has
    # none while its local-grid siblings open with '# source: ...', so an
    # unconditional skip would eat this file's header row.
    body = [ln for ln in raw if ln.strip() and not _is_comment(ln)]
    delimiter = detect_delimiter(body)
    rows = [split_row(ln, delimiter) for ln in body]
    has_header = detect_header(rows)
    header = rows[0] if has_header else []
    data = rows[1:] if has_header else rows
    width = max((len(r) for r in rows), default=0)

    roles = detect_roles(header) if has_header else {}
    d_columns = detect_d_columns(header) if has_header else []

    profile = dfields.PROFILE_STRING
    if d_columns:
        counts = []
        for row in data:
            present = [row[i] for i in d_columns if i < len(row)]
            while present and not present[-1].strip():
                present.pop()
            d4 = row[d_columns[3]] if len(d_columns) > 3 and \
                d_columns[3] < len(row) else None
            counts.append((len(present), d4))
        profile = dfields.detect_profile(counts)

    en_order = None
    if ROLE_X in roles and ROLE_Y in roles:
        xs = [_as_float(r, roles[ROLE_X]) for r in data]
        ys = [_as_float(r, roles[ROLE_Y]) for r in data]
        en_order = guess_en_order(xs, ys)

    return {
        'delimiter': delimiter,
        'has_header': has_header,
        'header': header,
        'rows': data[:_SAMPLE_LINES],
        'width': width,
        'roles': roles,
        'd_columns': d_columns,
        'profile': profile,
        'signature': signature(delimiter, has_header, header, width),
        'en_order': en_order,
    }


def _as_float(row, index):
    if index is None or index >= len(row):
        return None
    try:
        return float(row[index].strip())
    except (TypeError, ValueError):
        return None


def sniff(path):
    """Confidence that this is a delimited coordinate file."""
    try:
        info = inspect(path)
    except OSError:
        return 0.0
    if not info['rows']:
        return 0.0
    roles = info['roles']
    if ROLE_X in roles and ROLE_Y in roles:
        return 0.9
    numeric = sum(1 for f in info['rows'][0] if _is_number(f))
    if numeric >= 3:
        return 0.6
    return 0.2


def apply_preset(name, width):
    """{role: index} from a classic ordering, trimmed to the actual width."""
    order = PRESETS.get((name or '').upper())
    if not order:
        return {}
    return {role: i for i, role in enumerate(order) if i < width}


def read_file(path, companions=None, level=None, mapping=None,
              group_strings=False, swap_en=False, **_options):
    """Read a delimited file into one ParsedFile.

    mapping: {role: column index}; defaults to what inspect() detected.
    group_strings: opt in to building polylines from the string column.
    swap_en: exchange the X and Y columns (set by the mapping dialog when the
             user confirms the file is northing-first).
    """
    name = os.path.basename(path)
    info = inspect(path)
    warnings = []

    roles = dict(info['roles'])
    if mapping:
        roles.update({k: v for k, v in mapping.items() if v is not None})
    if swap_en and ROLE_X in roles and ROLE_Y in roles:
        roles[ROLE_X], roles[ROLE_Y] = roles[ROLE_Y], roles[ROLE_X]

    if ROLE_X not in roles or ROLE_Y not in roles:
        raise RuntimeError(
            '{0}: could not work out which columns hold easting and northing. '
            'Set them in the column mapping.'.format(name))

    raw = read_lines(path)
    body = [ln for ln in raw if ln.strip() and not _is_comment(ln)]
    rows = [split_row(ln, info['delimiter']) for ln in body]
    if info['has_header']:
        rows = rows[1:]

    d_columns = info['d_columns']
    profile = info['profile']
    xi, yi = roles[ROLE_X], roles[ROLE_Y]
    zi = roles.get(ROLE_Z)
    idi = roles.get(ROLE_ID)
    codei = roles.get(ROLE_CODE)
    stringi = roles.get(ROLE_STRING) if group_strings else None

    records = []
    skipped = 0
    for row in rows:
        x = _as_float(row, xi)
        y = _as_float(row, yi)
        if x is None or y is None:
            skipped += 1
            continue
        attrs = {}
        if d_columns:
            values = [row[i] if i < len(row) else '' for i in d_columns]
            attrs.update(dfields.parse(values, profile))
        if idi is not None and idi < len(row) and row[idi].strip():
            attrs['PointId'] = row[idi].strip()
        if codei is not None and codei < len(row) and row[codei].strip():
            attrs['Code'] = row[codei].strip()
        string_no = None
        if ROLE_STRING in roles:
            raw_no = row[roles[ROLE_STRING]] if roles[ROLE_STRING] < len(row) \
                else ''
            try:
                string_no = int(float(raw_no))
                attrs['StringNo'] = string_no
            except (TypeError, ValueError):
                string_no = raw_no.strip() or None
        records.append(((x, y, _as_float(row, zi)), attrs, string_no))

    if skipped:
        warnings.append('{0}: {1} row(s) had no usable coordinates and were '
                        'skipped'.format(name, skipped))

    polylines = []
    stations = []
    if stringi is not None:
        # Group by RUNS of equal value, not by global value: survey exports
        # reuse string numbers for strings that are not connected.
        for points, attrs_list, string_no in _runs(records):
            if len(points) < 2:
                for point, attrs in zip(points, attrs_list):
                    stations.append(Station(point, attrs))
                continue
            polylines.append(Polyline(
                points=points,
                attrs=merge_attrs({'PointCount': len(points)},
                                  attrs_list[0] if attrs_list else {}),
                closed=is_closed(points)))
    else:
        stations = [Station(point, attrs) for point, attrs, _no in records]

    if level is not None:
        # Fallback only — a record carrying its own level keeps it.
        stamp = {'Level': level}
        polylines = [p._replace(attrs=merge_attrs(stamp, p.attrs))
                     for p in polylines]
        stations = [s._replace(attrs=merge_attrs(stamp, s.attrs))
                    for s in stations]

    return ParsedFile(
        path=path,
        name=name,
        format_key=FORMAT_KEY,
        polylines=tuple(polylines),
        stations=tuple(stations),
        surfaces=(),
        annotations=(),
        attrs={'delimiter': info['delimiter'],
               'has_header': info['has_header'],
               'profile': profile,
               'signature': info['signature'],
               'roles': {k: v for k, v in sorted(roles.items())},
               'group_strings': bool(stringi is not None)},
        warnings=tuple(warnings),
    )


def _runs(records):
    """Split records into consecutive runs sharing a string value."""
    out = []
    points = []
    attrs_list = []
    current = object()
    for point, attrs, string_no in records:
        if string_no != current and points:
            out.append((points, attrs_list, current))
            points, attrs_list = [], []
        current = string_no
        points.append(point)
        attrs_list.append(attrs)
    if points:
        out.append((points, attrs_list, current))
    return out
