"""
AutoCAD DXF reader.

DXF is the universal interchange for mine design and survey: Deswik, Vulcan,
Datamine, Micromine and AutoCAD all export it, and the layer name carries the
category (floor string, backs, pegs, stopes).

Pure python, streaming, no dependency
-------------------------------------
The ENTITIES section is just alternating lines of (group code, value), so a
correct reader for the entities that matter is a few hundred lines and needs
no ezdxf. That keeps DXF unit-testable with inline fixtures — which matters
more here than anywhere else, because DXF is the format most likely to meet
strange real-world files. GDAL's DXF driver is used only as an escape hatch
(binary DXF, or when a file defeats this reader); see ogr_fallback.py.

Streaming is not optional: real survey exports run to hundreds of megabytes
(ClipPegs.DXF is 398 MB), so nothing here reads the file into memory and
progress is reported by byte offset.

Entity routing
--------------
    LWPOLYLINE, POLYLINE, LINE          -> polylines
    POINT                               -> stations
    TEXT, MTEXT                         -> annotations
    3DFACE, POLYLINE polyface mesh      -> surfaces

Blocks are expanded. Mine-package DXF exports routinely wrap an entire
drawing in one block and reference it with a single INSERT at the origin —
MP_All Drives.DXF is 5 MB of drives inside one such block — so treating an
INSERT as a point would throw the whole file away. An INSERT whose block
holds no drawable geometry still becomes a station at its insertion point,
which is the right reading of a survey peg symbol.
"""

import os
import re

try:  # package context
    from ..ir import (Annotation, ParsedFile, Polyline, Station, Surface,
                      is_closed, merge_attrs)
except ImportError:  # loaded directly by path
    from ir import (Annotation, ParsedFile, Polyline, Station, Surface,
                    is_closed, merge_attrs)

FORMAT_KEY = 'dxf'

# Binary DXF opens with this sentinel; it is not parseable as group-code text.
BINARY_SENTINEL = b'AutoCAD Binary DXF'

# Runaway guard for a corrupt or unexpectedly huge file. Reached only by
# files far larger than any real survey export; the count is reported rather
# than silently truncating.
DEFAULT_MAX_ENTITIES = 2000000

# $DWGCODEPAGE values seen in the wild -> python codecs. Anything unknown
# falls back to cp1252, which covers Western-European AutoCAD exports.
_CODEPAGES = {
    'ANSI_1252': 'cp1252', 'ANSI_1250': 'cp1250', 'ANSI_1251': 'cp1251',
    'ANSI_1253': 'cp1253', 'ANSI_1254': 'cp1254', 'ANSI_1255': 'cp1255',
    'ANSI_1256': 'cp1256', 'ANSI_1257': 'cp1257', 'ANSI_1258': 'cp1258',
    'UTF8': 'utf-8', 'ANSI_874': 'cp874', 'ANSI_932': 'cp932',
    'ANSI_936': 'cp936', 'ANSI_949': 'cp949', 'ANSI_950': 'cp950',
}

# Layer-name tokens that route an entity somewhere other than its geometry
# would suggest. Applied case-insensitively as substrings.
LAYER_STATION_TOKENS = ('peg', 'station', 'stn', 'pickup', 'control',
                        'survey_point', 'surveypoint')
LAYER_TEXT_TOKENS = ('text', 'anno', 'label', 'note', 'annotation')

_LEVEL_IN_NAME = re.compile(r'(\d{3,4})')


def is_binary(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read(len(BINARY_SENTINEL)) == BINARY_SENTINEL
    except OSError:
        return False


def detect_encoding(path):
    """Read $DWGCODEPAGE from the HEADER section without decoding the file."""
    try:
        with open(path, 'rb') as fh:
            head = fh.read(64 * 1024)
    except OSError:
        return 'cp1252'
    if head.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    marker = head.find(b'$DWGCODEPAGE')
    if marker < 0:
        return 'cp1252'
    tail = head[marker:marker + 200].split(b'\n')
    # $DWGCODEPAGE, then a group code line (3), then the value.
    for chunk in tail[1:4]:
        value = chunk.strip().decode('ascii', 'replace').upper()
        if value in _CODEPAGES:
            return _CODEPAGES[value]
    return 'cp1252'


def group_codes(fh):
    """Yield (int code, str value) pairs from an open text DXF.

    Malformed pairs are skipped rather than raising: a truncated export
    should give up what it has, not nothing.
    """
    while True:
        code_line = fh.readline()
        if not code_line:
            return
        value_line = fh.readline()
        if not value_line:
            return
        try:
            code = int(code_line.strip())
        except ValueError:
            continue
        yield code, value_line.rstrip('\r\n')


def sniff(path):
    """Confidence that this is a DXF we can read."""
    if is_binary(path):
        return 0.5  # real DXF, but the OGR fallback has to handle it
    try:
        with open(path, 'r', encoding='cp1252', errors='replace') as fh:
            head = fh.read(4096).upper()
    except OSError:
        return 0.0
    if 'SECTION' in head and ('HEADER' in head or 'ENTITIES' in head):
        return 0.9
    return 0.1


def level_from_layer(layer_name):
    """A 3-4 digit run in a layer name is almost always the mine level."""
    match = _LEVEL_IN_NAME.search(layer_name or '')
    return match.group(1) if match else None


def apply_layer_rules(layer_name, rules=None):
    """(kind_override, level) for a layer name.

    kind_override is 'stations' / 'text' / None. rules is an optional
    [(regex, kind, level)] the dialog can supply; the built-in token lists are
    the fallback, so an unconfigured import still routes sensibly.
    """
    name = (layer_name or '')
    lowered = name.lower()
    for pattern, kind, level in (rules or ()):
        try:
            if re.search(pattern, name, re.IGNORECASE):
                return kind, level or level_from_layer(name)
        except re.error:
            continue
    if any(token in lowered for token in LAYER_TEXT_TOKENS):
        return 'text', level_from_layer(name)
    if any(token in lowered for token in LAYER_STATION_TOKENS):
        return 'stations', level_from_layer(name)
    return None, level_from_layer(name)


class _Entity(object):
    """Accumulates group codes for one entity."""

    __slots__ = ('type', 'layer', 'points', 'x', 'y', 'z', 'flags',
                 'elevation', 'text', 'height', 'rotation', 'name',
                 'scale', 'faces', 'extrusion', 'vertex_flags')

    def __init__(self, etype):
        self.type = etype
        self.layer = ''
        self.points = []       # [[x, y, z]] accumulated from 10/20/30
        self.x = self.y = self.z = None
        self.flags = 0
        self.elevation = None
        self.text = ''
        self.height = None
        self.rotation = None
        self.name = ''
        self.scale = [1.0, 1.0, 1.0]
        self.faces = []
        self.extrusion = None
        self.vertex_flags = 0


def _flush_point(entity):
    if entity.x is not None and entity.y is not None:
        entity.points.append([entity.x, entity.y, entity.z])
    entity.x = entity.y = entity.z = None


def _feed(entity, code, value):
    """Apply one group code to the entity being built."""
    if code == 8:
        entity.layer = value.strip()
    elif code == 10:
        # A new 10 starts a new point; flush whatever was accumulating.
        if entity.x is not None:
            _flush_point(entity)
        entity.x = _num(value)
    elif code == 20:
        entity.y = _num(value)
    elif code == 30:
        entity.z = _num(value)
    elif code in (11, 12, 13):
        # Secondary corners (LINE's end point, 3DFACE's corners 2-4). The
        # primary 10/20/30 point is still pending, so flush it first or the
        # corners come out in the wrong order.
        if entity.x is not None:
            _flush_point(entity)
        entity.points.append([_num(value), None, None])
    elif code in (21, 22, 23):
        if entity.points:
            entity.points[-1][1] = _num(value)
    elif code in (31, 32, 33):
        if entity.points:
            entity.points[-1][2] = _num(value)
    elif code == 38:
        entity.elevation = _num(value)
    elif code == 39:
        pass  # thickness, not needed
    elif code == 70:
        entity.flags = _int(value)
    elif code in (71, 72, 73, 74) and entity.type == 'VERTEX':
        index = _int(value)
        if index:
            entity.faces.append(index)
    elif code == 1:
        entity.text = value
    elif code == 3:
        entity.text = (entity.text or '') + value  # MTEXT continuation
    elif code == 40:
        entity.height = _num(value)
    elif code == 50:
        entity.rotation = _num(value)
    elif code == 2:
        entity.name = value.strip()
    elif code == 41:
        entity.scale[0] = _num(value) or 1.0
    elif code == 42:
        entity.scale[1] = _num(value) or 1.0
    elif code == 43:
        entity.scale[2] = _num(value) or 1.0
    elif code == 210:
        entity.extrusion = [_num(value), None, None]
    elif code == 220 and entity.extrusion:
        entity.extrusion[1] = _num(value)
    elif code == 230 and entity.extrusion:
        entity.extrusion[2] = _num(value)


def _num(value):
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return None


def _int(value):
    try:
        return int(float(value.strip()))
    except (TypeError, ValueError):
        return 0


def _finish(entity):
    _flush_point(entity)
    # A 2D LWPOLYLINE carries one elevation for the whole polyline.
    if entity.elevation is not None:
        for point in entity.points:
            if point[2] is None:
                point[2] = entity.elevation
    return entity


def _as_tuples(points):
    return [(p[0], p[1], p[2]) for p in points
            if p[0] is not None and p[1] is not None]


# Entity types we build geometry from. Anything else is counted and skipped,
# so an unhandled type shows up in the summary rather than vanishing.
_HANDLED = frozenset((
    'LWPOLYLINE', 'POLYLINE', 'VERTEX', 'SEQEND', 'LINE', 'POINT', '3DFACE',
    'TEXT', 'MTEXT', 'INSERT'))

# Structural or non-geometric entities that carry nothing importable. Skipped
# silently, so the summary reports only entity types a user might actually
# have expected to see on the map.
_IGNORED = frozenset((
    'ATTDEF', 'ATTRIB', 'BLOCK', 'ENDBLK', 'VIEWPORT', 'DIMENSION',
    'HATCH', 'LEADER', 'MLEADER', 'XLINE', 'RAY', 'SPLINE', 'ELLIPSE',
    'SOLID', 'TRACE', 'SHAPE', 'TOLERANCE', 'IMAGE', 'WIPEOUT'))


class _Collector(object):
    """Turns a stream of finished entities into IR, tracking POLYLINE state."""

    # An INSERT inside a block inside a block... is legal but rare; this
    # stops a self-referencing file from recursing forever.
    MAX_BLOCK_DEPTH = 4

    def __init__(self, layer_rules=None, blocks=None):
        self.layer_rules = layer_rules
        self.blocks = blocks if blocks is not None else {}
        self.polylines = []
        self.stations = []
        self.annotations = []
        self.surfaces = []
        self.skipped = {}
        self.layers = {}
        self._poly = None        # open POLYLINE header
        self._vertices = []      # its VERTEX entities
        self._faces = {}         # layer -> accumulating triangle soup
        self.entity_count = 0
        self._depth = 0

    # -- helpers --------------------------------------------------------

    def _attrs(self, entity, extra=None):
        kind, level = apply_layer_rules(entity.layer, self.layer_rules)
        attrs = {'SrcLayer': entity.layer}
        if level:
            attrs['Level'] = level
        if extra:
            attrs.update(extra)
        return kind, attrs

    def _note_layer(self, entity):
        self.layers[entity.layer] = self.layers.get(entity.layer, 0) + 1

    def _drawn(self):
        """How much geometry exists so far, including un-flushed faces.

        3DFACEs accumulate into a per-layer soup rather than becoming
        surfaces immediately, so a naive len(self.surfaces) would report a
        block full of faces as empty and add a spurious station for it —
        427,318 of them in the case of ClipPegs.DXF.
        """
        pending = sum(len(soup['triangles']) for soup in self._faces.values())
        return (len(self.polylines) + len(self.stations)
                + len(self.surfaces) + len(self.annotations) + pending)

    def _add_line(self, entity, points):
        kind, attrs = self._attrs(entity, {'PointCount': len(points)})
        if kind == 'stations':
            # A layer named for pegs holds pegs even when the exporter drew
            # them as tiny polylines.
            for point in points:
                self.stations.append(Station(point, dict(attrs)))
            return
        self.polylines.append(Polyline(
            points=points, attrs=attrs,
            closed=bool(entity.flags & 1) or is_closed(points)))

    def _add_station(self, entity, point, extra=None):
        _kind, attrs = self._attrs(entity, extra)
        self.stations.append(Station(point, attrs))

    def _add_text(self, entity, point):
        _kind, attrs = self._attrs(entity, {
            'Height': entity.height, 'Rotation': entity.rotation})
        self.annotations.append(
            Annotation(point, _clean_mtext(entity.text), attrs))

    # -- entity dispatch -------------------------------------------------

    def add(self, entity):
        etype = entity.type
        if etype not in _HANDLED:
            if etype not in _IGNORED:
                self.skipped[etype] = self.skipped.get(etype, 0) + 1
            return
        self.entity_count += 1
        self._note_layer(entity)

        if etype == 'POLYLINE':
            self._close_polyline()
            self._poly = entity
            self._vertices = []
            return
        if etype == 'VERTEX':
            if self._poly is not None:
                self._vertices.append(entity)
            return
        if etype == 'SEQEND':
            self._close_polyline()
            return

        # A stray entity between POLYLINE and SEQEND ends the polyline: some
        # exporters omit SEQEND entirely.
        self._close_polyline()

        if etype == 'LWPOLYLINE':
            points = _as_tuples(entity.points)
            if len(points) >= 2:
                self._add_line(entity, points)
            elif points:
                self._add_station(entity, points[0])
            return
        if etype == 'LINE':
            points = _as_tuples(entity.points)
            if len(points) >= 2:
                self._add_line(entity, points[:2])
            return
        if etype == 'POINT':
            points = _as_tuples(entity.points)
            if points:
                self._add_station(entity, points[0])
            return
        if etype == 'INSERT':
            self._expand_insert(entity)
            return
        if etype in ('TEXT', 'MTEXT'):
            points = _as_tuples(entity.points)
            if points and entity.text:
                self._add_text(entity, points[0])
            return
        if etype == '3DFACE':
            points = _as_tuples(entity.points)
            if len(points) >= 3:
                self._add_face(entity, points)
            return

    def _expand_insert(self, insert):
        """Replay a block's entities at the insertion point.

        Mine-package exports commonly put an entire drawing in one block and
        INSERT it once at the origin, so not expanding would discard the
        file. A block with nothing drawable in it is a symbol, and its
        insertion point is the surveyed position — that becomes a station.
        """
        points = _as_tuples(insert.points)
        origin = points[0] if points else (0.0, 0.0, 0.0)
        body = self.blocks.get((insert.name or '').upper())

        if not body or self._depth >= self.MAX_BLOCK_DEPTH:
            self._add_station(
                insert, origin,
                {'Code': insert.name} if insert.name else None)
            return

        base, entities = body
        transform = _make_transform(origin, base, insert.scale,
                                    insert.rotation)
        before = self._drawn()
        self._depth += 1
        try:
            for source in entities:
                clone = _transformed(source, transform)
                # The INSERT's own layer wins when the block's entities sit
                # on layer '0', which is the AutoCAD convention for
                # "inherit from the reference".
                if clone.layer in ('', '0') and insert.layer:
                    clone.layer = insert.layer
                self.add(clone)
            self._close_polyline()
        finally:
            self._depth -= 1

        if self._drawn() == before:
            # Block drew nothing: treat the reference as a point symbol.
            self._add_station(
                insert, origin,
                {'Code': insert.name} if insert.name else None)

    def _add_face(self, entity, points):
        """Accumulate a 3DFACE into its layer's triangle soup.

        Emphatically NOT one Surface per face. Face-based exports run to
        hundreds of thousands of 3DFACEs — ClipPegs.DXF is 427,318 of them,
        one per block — and a Surface each would mean a quarter of a million
        single-triangle polygons to dissolve. They are all one mesh.

        Vertices are welded on rounded coordinates so shared corners collapse
        instead of being repeated per face.
        """
        soup = self._faces.get(entity.layer)
        if soup is None:
            soup = self._faces[entity.layer] = {'points': [], 'index': {},
                                                'triangles': []}
        index = soup['index']
        points_list = soup['points']

        def vertex(point):
            key = (round(point[0], 4), round(point[1], 4),
                   round(point[2], 4) if point[2] is not None else None)
            found = index.get(key)
            if found is None:
                found = index[key] = len(points_list)
                points_list.append(point)
            return found

        corners = [vertex(p) for p in points[:4]]
        triangles = soup['triangles']
        if corners[0] != corners[1] and corners[1] != corners[2]:
            triangles.append((corners[0], corners[1], corners[2]))
        # Corner 4 repeating corner 1 is how a triangle is written as a quad.
        if len(corners) >= 4 and corners[3] not in (corners[0], corners[2]):
            triangles.append((corners[0], corners[2], corners[3]))

    def _flush_faces(self):
        for layer, soup in self._faces.items():
            if not soup['triangles']:
                continue
            entity = _Entity('3DFACE')
            entity.layer = layer
            _kind, attrs = self._attrs(
                entity, {'TriangleCount': len(soup['triangles'])})
            self.surfaces.append(
                Surface(soup['points'], soup['triangles'], attrs))
        self._faces = {}

    def _close_polyline(self):
        if self._poly is None:
            return
        header, vertices = self._poly, self._vertices
        self._poly, self._vertices = None, []
        if not vertices:
            return
        # Some exporters put the layer on the vertices and leave the POLYLINE
        # header bare; without this the whole string loses its category.
        if not header.layer:
            for vertex in vertices:
                if vertex.layer:
                    header.layer = vertex.layer
                    break
        # Bit 6 (64) marks a polyface mesh: its vertices are either mesh
        # vertices or face-index records, not a path.
        if header.flags & 64:
            self._add_polyface(header, vertices)
            return
        points = []
        for vertex in vertices:
            got = _as_tuples(vertex.points)
            if got:
                points.append(got[0])
        if len(points) >= 2:
            self._add_line(header, points)
        elif points:
            self._add_station(header, points[0])

    def _add_polyface(self, header, vertices):
        mesh_points = []
        faces = []
        for vertex in vertices:
            if vertex.faces:
                # Face record: 1-based indices, negative marks an invisible
                # edge and is still a real vertex.
                idx = [abs(i) - 1 for i in vertex.faces if i]
                if len(idx) >= 3:
                    faces.append((idx[0], idx[1], idx[2]))
                    if len(idx) >= 4 and idx[3] != idx[2]:
                        faces.append((idx[0], idx[2], idx[3]))
                continue
            got = _as_tuples(vertex.points)
            if got:
                mesh_points.append(got[0])
        limit = len(mesh_points)
        faces = [f for f in faces if all(0 <= i < limit for i in f)]
        if mesh_points and faces:
            _kind, attrs = self._attrs(header, {'TriangleCount': len(faces)})
            self.surfaces.append(Surface(mesh_points, faces, attrs))

    def finish(self):
        self._close_polyline()
        self._flush_faces()


def _make_transform(origin, base, scale, rotation):
    """Block-space -> world-space mapping for one INSERT.

    Translation, per-axis scale and rotation about Z, which is what survey
    and mine-design exports use. A general 3D transform would need the OCS
    extrusion handled too; that case warns and imports unrotated instead of
    silently placing geometry wrongly.
    """
    import math
    angle = math.radians(rotation or 0.0)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    sx, sy, sz = (scale or [1.0, 1.0, 1.0])
    bx, by, bz = base

    def transform(point):
        x, y, z = point
        if x is None or y is None:
            return (x, y, z)
        dx = (x - bx) * sx
        dy = (y - by) * sy
        return (origin[0] + dx * cos_a - dy * sin_a,
                origin[1] + dx * sin_a + dy * cos_a,
                None if z is None
                else (origin[2] or 0.0) + (z - bz) * sz)

    return transform


def _transformed(source, transform):
    """A shallow copy of an entity with its points mapped into world space."""
    clone = _Entity(source.type)
    clone.layer = source.layer
    clone.flags = source.flags
    clone.text = source.text
    clone.height = source.height
    clone.rotation = source.rotation
    clone.name = source.name
    clone.faces = list(source.faces)
    clone.points = [list(transform((p[0], p[1], p[2])))
                    for p in source.points]
    # Elevation is already folded into the points by _finish().
    return clone


_MTEXT_CODES = re.compile(r'\\[A-Za-z][^;\\]*;|\\[PpXx]|[{}]')


def _clean_mtext(text):
    """Strip MTEXT formatting codes, leaving the readable string."""
    if not text:
        return ''
    return _MTEXT_CODES.sub(' ', text).replace('\\~', ' ').strip()


def parse_stream(fh, layer_rules=None, max_entities=DEFAULT_MAX_ENTITIES,
                 progress_cb=None, total_bytes=0):
    """Parse an open text DXF into a _Collector. Streams; never readlines()."""
    blocks = {}
    collector = _Collector(layer_rules=layer_rules, blocks=blocks)
    section = None
    entity = None
    in_entities = False
    in_blocks = False
    expect_section_name = False
    truncated = False
    checked = 0
    # BLOCKS precedes ENTITIES in a well-formed DXF, so one pass suffices.
    block_name = None
    block_base = (0.0, 0.0, 0.0)
    block_body = []

    def close_block():
        if block_name:
            blocks[block_name.upper()] = (block_base, list(block_body))

    for code, value in group_codes(fh):
        if code == 0:
            token = value.strip().upper()
            if entity is not None:
                finished = _finish(entity)
                entity = None
                if in_blocks:
                    if finished.type == 'BLOCK':
                        close_block()
                        got = _as_tuples(finished.points)
                        block_name = finished.name
                        block_base = got[0] if got else (0.0, 0.0, 0.0)
                        block_body = []
                    elif finished.type == 'ENDBLK':
                        close_block()
                        block_name, block_body = None, []
                    elif block_name:
                        block_body.append(finished)
                else:
                    collector.add(finished)
                    if collector.entity_count >= max_entities:
                        truncated = True
                        break
            if token == 'SECTION':
                expect_section_name = True
                continue
            if token == 'ENDSEC':
                if in_blocks:
                    close_block()
                    block_name, block_body = None, []
                section, in_entities, in_blocks = None, False, False
                continue
            if token == 'EOF':
                break
            if in_entities or in_blocks:
                entity = _Entity(token)
            continue
        if expect_section_name and code == 2:
            section = value.strip().upper()
            in_entities = section == 'ENTITIES'
            in_blocks = section == 'BLOCKS'
            expect_section_name = False
            continue
        if entity is not None:
            _feed(entity, code, value)

        checked += 1
        if progress_cb is not None and total_bytes and checked % 20000 == 0:
            try:
                progress_cb(min(90, int(90.0 * fh.tell() / total_bytes)), None)
            except (OSError, ValueError):
                pass

    if entity is not None:
        finished = _finish(entity)
        if in_blocks and block_name:
            block_body.append(finished)
        elif not in_blocks:
            collector.add(finished)
    if in_blocks:
        close_block()
    collector.finish()
    return collector, truncated


def read_file(path, companions=None, level=None, layer_rules=None,
              max_entities=DEFAULT_MAX_ENTITIES, progress_cb=None,
              **_options):
    """Read a DXF into one ParsedFile."""
    name = os.path.basename(path)
    if is_binary(path):
        raise RuntimeError(
            '{0} is a binary DXF, which this reader cannot read. Re-export it '
            'as ASCII DXF, or tick "Use GDAL DXF reader".'.format(name))

    encoding = detect_encoding(path)
    try:
        total_bytes = os.path.getsize(path)
    except OSError:
        total_bytes = 0

    with open(path, 'r', encoding=encoding, errors='replace') as fh:
        collector, truncated = parse_stream(
            fh, layer_rules=layer_rules, max_entities=max_entities,
            progress_cb=progress_cb, total_bytes=total_bytes)

    warnings = []
    if truncated:
        warnings.append(
            '{0}: stopped after {1} entities — the file is larger than the '
            'import limit and was not read in full.'.format(
                name, max_entities))
    if collector.skipped:
        listed = ', '.join('{0}x{1}'.format(v, k) for k, v in
                           sorted(collector.skipped.items(),
                                  key=lambda kv: -kv[1])[:6])
        warnings.append('{0}: skipped unsupported entities ({1})'.format(
            name, listed))
    if not (collector.polylines or collector.stations or collector.surfaces
            or collector.annotations):
        warnings.append('{0}: no drawable entities found'.format(name))

    polylines = list(collector.polylines)
    stations = list(collector.stations)
    surfaces = list(collector.surfaces)
    annotations = list(collector.annotations)

    if level is not None:
        # Fallback only: a layer name carrying its own level keeps it.
        stamp = {'Level': level}
        polylines = [p._replace(attrs=merge_attrs(stamp, p.attrs))
                     for p in polylines]
        stations = [s._replace(attrs=merge_attrs(stamp, s.attrs))
                    for s in stations]
        surfaces = [s._replace(attrs=merge_attrs(stamp, s.attrs))
                    for s in surfaces]
        annotations = [a._replace(attrs=merge_attrs(stamp, a.attrs))
                       for a in annotations]

    return ParsedFile(
        path=path,
        name=name,
        format_key=FORMAT_KEY,
        polylines=tuple(polylines),
        stations=tuple(stations),
        surfaces=tuple(surfaces),
        annotations=tuple(annotations),
        attrs={'encoding': encoding,
               'layers': dict(sorted(collector.layers.items())[:200]),
               'skipped_entities': dict(collector.skipped)},
        warnings=tuple(warnings),
    )
