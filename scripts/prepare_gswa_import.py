"""A GSWA 1:100k mapsheet package, turned into something Import Mapping Data can swallow.

GSWA ship their geology as shapefiles with almost nothing on them: the polygon
layer carries CODE, JNCODE and fme_featur, and that is all. Every attribute a
geologist would recognise - unit name, rock type, lithology, regolith class,
stratigraphy, age - lives in a separate CSV lookup table joined on CODE.

The LGS importer maps one source column to one destination column. It has no
join and no expression engine (data_import/derive.py), by design: the whole
point of that tool is that a human sees and approves every code decision, and
an expression language would smuggle decisions past them. So the join has to
happen before the wizard sees the data, and this is where it happens.

What comes out is one GeoPackage with two layers named exactly "4 - Basemap"
and "2 - Linework", whose columns are named exactly after the destination
fields. That is not cosmetic: match_layers.score_pair() gives a canonical name
+1000 and match_fields tier 1 claims an identically named column, so the wizard
pairs everything itself and Step 4 has nothing left to decide.

The transposition itself is GSWA_POLY / GSWA_LINE / GSWA_DYKE below - one row
per GSWA map unit, written out so it can be argued with. Anything this file
does not recognise falls back to the generic tables (LITH_BY_NAME,
REGOLITH_BY_FAMILY) and is reported at the end rather than silently dropped,
which is what lets the script survive a different mapsheet.

Two things deliberately NOT written:

  TypeLith1/TypeLith2 - derive.fill_parents() back-fills them from
    BasemapCodes.Type, and that back-fill is what puts the T* units on the
    cover side of the cover-vs-bedrock gate and the R* units on the bedrock
    side. Writing them by hand would only be a second chance to get it wrong.

  Description - the template fills it from BasemapCodes with a get_feature()
    default, and a default only fires into a blank attribute
    (execute._build_feature). Feeding Description from source would suppress
    the LGS code description. GSWA's own DESCRIPTN goes to Comments instead.

Usage:  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" scripts\\prepare_gswa_import.py \\
            <path to the unzipped GSWA mapsheet folder> <output.gpkg>
"""
import csv
import glob
import os
import re
import sys
import uuid
import warnings

try:
    from osgeo import ogr
except ImportError:
    # The mapping tables below are the part worth checking, and checking them
    # against the shipped template needs no GDAL. tests/test_gswa_mapping.py
    # imports this module that way.
    ogr = None

# Neither ogr.UseExceptions() nor DontUseExceptions() is called here. Both go
# through _has_gdal_array(), which on OSGeo4W imports a gdal_array built
# against NumPy 1.x and makes NumPy 2 print forty lines of warning before
# failing harmlessly. Every GDAL call below checks its return value instead,
# which is what the default error mode needs; this silences GDAL's nudge to
# choose, since choosing is what costs the noise.
warnings.filterwarnings('ignore', category=FutureWarning, module='osgeo')

BASEMAP_LAYER = '4 - Basemap'
LINEWORK_LAYER = '2 - Linework'

# Comments is TEXT(500) on both layers. SQLite will not enforce that but the
# QGIS provider truncates on write, so truncate here where it is visible.
COMMENT_LIMIT = 500

# uuid5 rather than uuid4: GSWA data carries no UUID, and with a fresh uuid4
# per run a second import would duplicate the whole sheet instead of being
# recognised as already present (data_import/plan.py estimate_new).
UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL,
                            'https://lineargeoscience.au/gswa-import')


# ── the transposition ────────────────────────────────────────────────

# GSWA map unit -> (Lithology1, Lithology2, LithologyPrefix, mineral, texture).
#
# Prefix is what the LGS label grammar renders as "Ek-SSL" / "A1-TALL", and it
# is carrying two things LGS has no field for: the stratigraphic unit (Ek =
# Kiangi Creek Formation) and, for cover, the depositional generation - GSWA
# map three generations of alluvium that all collapse to TALL, and without the
# prefix they would be indistinguishable on the map.
#
# The mineral slot is GSWA's own suffix grammar: -f ferruginous, -k
# carbonate-rich, -n manganiferous.
GSWA_POLY = {
    # ── transported cover ───────────────────────────────────────────
    '_Ad':        ('TLAC', None,  'Ad',   None,  None),
    '_S':         ('TSA',  None,  'S',    None,  None),
    '_A1':        ('TALL', None,  'A1',   None,  None),
    '_A1-k':      ('TALL', None,  'A1k',  'Cb',  None),
    '_A2':        ('TALL', None,  'A2',   None,  None),
    '_A3':        ('TALL', None,  'A3',   None,  None),
    '_A3-f':      ('TALL', None,  'A3f',  'Gth', None),
    '_C1':        ('TCO',  None,  'C1',   None,  None),
    '_C1-f':      ('TLSC', None,  'C1f',  'Gth', None),
    '_C2':        ('TCO',  None,  'C2',   None,  None),
    '_C2-f':      ('TLSC', None,  'C2f',  'Gth', None),
    '_C3':        ('TCO',  None,  'C3',   None,  None),
    '_C3-f':      ('TLSC', None,  'C3f',  'Gth', None),
    '_C3-f-n':    ('TLSC', None,  'C3fn', 'Mn',  None),
    '_W':         ('TSW',  None,  'W',    None,  None),
    '_Wt':        ('TSW',  None,  'Wt',   None,  None),
    '_W-f':       ('TSW',  None,  'Wf',   'Gth', None),

    # ── regolith (in situ - stays on the bedrock side of the gate) ──
    '_R-f':       ('RFC',  None,  'Rf',   'Gth', None),
    '_R-f-n':     ('RFC',  None,  'Rfn',  'Mn',  None),
    '_R-k':       ('RCC',  None,  'Rk',   'Opl', None),

    # ── bedrock: Edmund Group ───────────────────────────────────────
    'P_-MEi-kd':  ('SDO',  None,  'Ei',   None,  None),
    'P_-MEi-sl':  ('SSL',  None,  'Ei',   None,  None),
    'P_-MEi-sf':  ('SSL',  'SST', 'Ei',   None,  'Interbedded'),
    'P_-MEi-ss':  ('SST',  'SSL', 'Ei',   None,  'Interbedded'),
    'P_-MEiw-st': ('SST',  None,  'Eiw',  None,  None),
    'P_-MEk-kd':  ('SDO',  None,  'Ek',   None,  None),
    'P_-MEk-sl':  ('SSL',  None,  'Ek',   None,  None),
    'P_-MEk-sli': ('SSL',  None,  'Ek',   'Gth', None),
    'P_-MEk-sf':  ('SSL',  'SST', 'Ek',   None,  'Interbedded'),
    'P_-MEk-ss':  ('SST',  'SSL', 'Ek',   None,  'Interbedded'),
    'P_-MEk-st':  ('SST',  None,  'Ek',   None,  None),
    'P_-MEk-stq': ('SSTQ', None,  'Ek',   None,  None),
    'P_-MEk-sp':  ('SST',  'SCG', 'Ek',   None,  'Interbedded'),
    'P_-MEl-sl':  ('SSL',  None,  'El',   None,  None),
    'P_-MEl-ss':  ('SST',  'SSL', 'El',   None,  'Interbedded'),
    'P_-MEv-kd':  ('SDO',  None,  'Ev',   None,  None),
    'P_-MEv-sl':  ('SSL',  None,  'Ev',   None,  None),
    'P_-MEd-cl':  ('SCT',  'SMD', 'Ed',   None,  'Interbedded'),
    'P_-MEy-st':  ('SST',  None,  'Ey',   None,  None),
    'P_-MEy-mts': ('SPS',  None,  'Ey',   None,  'Schistose'),

    # ── bedrock: Collier Group, dolerite, granite ───────────────────
    'P_-MCb-st':  ('SST',  None,  'Cb',   None,  None),
    'P_-_nr-od':  ('MD',   'MG',  'nr',   None,  None),
    'P_-MO-gmeb': ('FGM',  None,  'MO',   None,  'Equigranular'),
}

# Fallbacks for a mapsheet this file has not been told about. GSWA's LITHNAME1
# vocabulary is national, so most units on any sheet land here.
LITH_BY_NAME = {
    'siltstone/mudstone':                   ('SSL',  None),
    'mudstone':                             ('SMD',  None),
    'shale':                                ('SSH',  None),
    'sandstone':                            ('SST',  None),
    'sandstone + siltstone':                ('SST',  'SSL'),
    'siltstone + sandstone':                ('SSL',  'SST'),
    'sandstone + conglomerate':             ('SST',  'SCG'),
    'conglomerate':                         ('SCG',  None),
    'dolostone/dolomite':                   ('SDO',  None),
    'limestone':                            ('SLI',  None),
    'chert':                                ('SCT',  None),
    'mixed chert and mudstone/siltstone':   ('SCT',  'SMD'),
    'quartzite':                            ('SQT',  None),
    'psammitic schist':                     ('SPS',  None),
    'dolerite':                             ('MD',   'MG'),
    'gabbro':                               ('MG',   None),
    'basalt':                               ('MB',   None),
    'monzogranite':                         ('FGM',  None),
    'granite':                              ('FGR',  None),
    'granodiorite':                         ('FGD',  None),
}

# GSWA's REGOLITH column names a landform family; that is enough to place an
# unrecognised regolith unit on the right side of the cover gate.
REGOLITH_BY_FAMILY = {
    'alluvial units':       'TALL',
    'colluvial units':      'TCO',
    'sheetwash units':      'TSW',
    'sandplain units':      'TSA',
    'eolian units':         'TAES',
    'lacustrine units':     'TLAC',
    'residual or relict units': 'RFC',
}

# GSWA's suffix grammar on a regolith code: -f ferruginous, -k carbonate,
# -n manganiferous. Read right to left, so _C3-f-n is manganiferous.
SUFFIX_MINERAL = (('-n', 'Mn'), ('-k', 'Cb'), ('-f', 'Gth'))

# GSWA linear FEATURE + TYPE -> (LineworkCodes.Code, Confidence, Weight).
# Weight is Major rather than the template's Moderate default because these
# are 100k-scale regional structures and Weight drives stroke scaling.
GSWA_LINE = {
    ('fault', 'exposed'):                       ('Fault',             'Observed', 'Major'),
    ('fault', 'concealed'):                     ('Fault - Concealed', 'Inferred', 'Major'),
    ('fold, showing axial trace', 'anticline, exposed'):   ('Anticline', 'Observed', 'Major'),
    ('fold, showing axial trace', 'anticline, concealed'): ('Anticline', 'Inferred', 'Major'),
    ('fold, showing axial trace', 'syncline, exposed'):    ('Syncline',  'Observed', 'Major'),
    ('fold, showing axial trace', 'syncline, concealed'):  ('Syncline',  'Inferred', 'Major'),
}

# A GSWA dyke is any unit too narrow to draw as a polygon, so the layer holds
# genuine dykes and thin sedimentary markers alike. Keyed on the dyke LUT's
# LITHNAME1, falling back to ROCKTYPE1.
DYKE_BY_LITHNAME = {
    'dolerite':   'Dolerite Dykes',
    'gabbro':     'Mafic Dykes',
    'granite':    'Felsic Dykes',
    'pegmatite':  'Pegmatite',
    'lamprophyre': 'Lamprophyre Dykes',
}
DYKE_BY_ROCKTYPE = {
    'igneous mafic intrusive':        'Mafic Dykes',
    'igneous ultramafic intrusive':   'Ultramafic Dykes',
    'igneous granitic':               'Felsic Dykes',
    'igneous felsic intrusive':       'Felsic Dykes',
    'igneous intermediate intrusive': 'Intermediate Dykes',
    # A thin sedimentary unit drawn as a line is a marker horizon. LGS has
    # Marker - BIF / Chert / Carbonaceous Shale but no clastic member, and one
    # feature does not justify a new code, so Sill is the least-wrong home.
    'sedimentary siliciclastic':      'Sill',
    'sedimentary carbonate':          'Sill',
}


# ── field layout of the two output layers ────────────────────────────

BASEMAP_FIELDS = (
    'Lithology1', 'Lithology2', 'LithologyPrefix',
    'Lith1Mineral1', 'Lith1Texture1',
    'MappedLithology1', 'Comments', 'ContactType',
    'MappedCRS', 'MappedScale', 'ProjectID', 'UUID',
)

LINEWORK_FIELDS = (
    'Type', 'Confidence', 'Weight', 'Label', 'Comments',
    'MappedCRS', 'MappedScale', 'ProjectID', 'UUID',
)


# ── reading the GSWA package ─────────────────────────────────────────

def find_package(root):
    """(shapefile dir, lut dir, sheet number) for an unzipped GSWA package."""
    shapes = os.path.join(root, 'ESRI', 'SHAPEFILES')
    luts = os.path.join(root, 'DATABASES', 'GEOL_LUT_CSV')
    if not os.path.isdir(shapes):
        raise SystemExit('no ESRI/SHAPEFILES under {0}'.format(root))
    if not os.path.isdir(luts):
        raise SystemExit('no DATABASES/GEOL_LUT_CSV under {0}'.format(root))
    found = glob.glob(os.path.join(shapes, 'geology_surface_*.shp'))
    if not found:
        raise SystemExit('no geology_surface_*.shp in {0}'.format(shapes))
    match = re.search(r'geology_surface_(\w+)\.shp$', found[0])
    return shapes, luts, match.group(1)


def read_lut(path):
    """GSWA lookup CSV as {CODE: row}. Empty dict if the file is absent."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding='utf-8-sig', newline='') as handle:
        return {row['CODE']: row for row in csv.DictReader(handle)
                if (row.get('CODE') or '').strip()}


def open_layer(shapes, stem, sheet):
    """(datasource, layer) for one GSWA shapefile, or (None, None)."""
    path = os.path.join(shapes, '{0}_{1}.shp'.format(stem, sheet))
    if not os.path.isfile(path):
        return None, None
    source = ogr.Open(path)
    if source is None:
        raise SystemExit('could not open {0}'.format(path))
    return source, source.GetLayer(0)


# ── the decisions ────────────────────────────────────────────────────

def suffix_mineral(code):
    """Gth / Cb / Mn from a GSWA regolith code's suffix, or None."""
    for suffix, mineral in SUFFIX_MINERAL:
        if code.endswith(suffix):
            return mineral
    return None


def polygon_codes(code, row):
    """(lith1, lith2, prefix, mineral, texture, how) for one GSWA map unit."""
    known = GSWA_POLY.get(code)
    if known:
        return known + ('table',)

    # Unknown unit on an unfamiliar sheet: place it from GSWA's own columns.
    prefix = code.lstrip('_').split('-')[0][:4] or None
    regolith = (row.get('REGOLITH') or '').strip().lower()
    if regolith:
        family = regolith.split(',')[0].strip()
        lith1 = REGOLITH_BY_FAMILY.get(family)
        if lith1:
            return lith1, None, prefix, suffix_mineral(code), None, 'regolith'

    name = (row.get('LITHNAME1') or '').strip().lower()
    pair = LITH_BY_NAME.get(name)
    if pair:
        return pair[0], pair[1], prefix, suffix_mineral(code), None, 'lithname'

    return None, None, prefix, None, None, 'unmapped'


def line_codes(feature_name, type_name):
    """(Type, Confidence, Weight, how) for one GSWA linear feature."""
    key = ((feature_name or '').strip().lower(), (type_name or '').strip().lower())
    known = GSWA_LINE.get(key)
    if known:
        return known + ('table',)

    feature_text, type_text = key
    concealed = 'concealed' in type_text or 'inferred' in type_text
    confidence = 'Inferred' if concealed else 'Observed'
    if 'fault' in feature_text:
        return ('Fault - Concealed' if concealed else 'Fault',
                confidence, 'Major', 'keyword')
    if 'anticline' in type_text:
        return 'Anticline', confidence, 'Major', 'keyword'
    if 'syncline' in type_text:
        return 'Syncline', confidence, 'Major', 'keyword'
    if 'fold' in feature_text:
        return 'Fold Axial Trace - Inferred', confidence, 'Major', 'keyword'
    if 'shear' in feature_text:
        return 'Shear', confidence, 'Major', 'keyword'
    return None, confidence, 'Major', 'unmapped'


def dyke_code(row):
    """LineworkCodes.Code for one GSWA dyke, from its lookup row."""
    name = (row.get('LITHNAME1') or '').strip().lower()
    if name in DYKE_BY_LITHNAME:
        return DYKE_BY_LITHNAME[name], 'table'
    rocktype = (row.get('ROCKTYPE1') or '').strip().lower()
    if rocktype in DYKE_BY_ROCKTYPE:
        return DYKE_BY_ROCKTYPE[rocktype], 'rocktype'
    return None, 'unmapped'


def comment_for(code, row):
    """The GSWA record, kept verbatim where a geologist can read it back."""
    parts = [code]
    for column in ('UNITNAME', 'GROUP_', 'SUPERGROUP', 'REGOLITH', 'DESCRIPTN'):
        value = (row.get(column) or '').strip()
        if value and value not in parts:
            parts.append(value)
    return ' | '.join(parts)[:COMMENT_LIMIT]


def stable_uuid(sheet, layer, key):
    return str(uuid.uuid5(UUID_NAMESPACE, '{0}:{1}:{2}'.format(sheet, layer, key)))


# ── writing ──────────────────────────────────────────────────────────

def create_output(path, srs):
    if os.path.exists(path):
        os.remove(path)
    driver = ogr.GetDriverByName('GPKG')
    target = driver.CreateDataSource(path)
    if target is None:
        raise SystemExit('could not create {0}'.format(path))
    layers = {}
    for name, geom_type, fields in (
            (BASEMAP_LAYER, ogr.wkbPolygon, BASEMAP_FIELDS),
            (LINEWORK_LAYER, ogr.wkbLineString, LINEWORK_FIELDS)):
        layer = target.CreateLayer(name, srs, geom_type)
        for field in fields:
            definition = ogr.FieldDefn(field, ogr.OFTString)
            definition.SetWidth(500 if field == 'Comments' else 250)
            layer.CreateField(definition)
        layers[name] = layer
    return target, layers


def write(layer, geometry, values):
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geometry)
    for field, value in values.items():
        if value is not None and value != '':
            feature.SetField(field, value)
    layer.CreateFeature(feature)


def build(root, out_path, project_id=None):
    shapes, luts, sheet = find_package(root)
    project_id = project_id or 'GSWA {0}'.format(sheet)

    poly_lut = read_lut(os.path.join(
        luts, 'geology_surface_{0}_lut.csv'.format(sheet)))
    dyke_lut = read_lut(os.path.join(
        luts, 'dyke_{0}_lut.csv'.format(sheet)))

    poly_source, poly_layer = open_layer(shapes, 'geology_surface', sheet)
    if poly_layer is None:
        raise SystemExit('no geology_surface layer for sheet {0}'.format(sheet))
    srs = poly_layer.GetSpatialRef()
    crs_name = 'EPSG:{0}'.format(srs.GetAuthorityCode(None) or '')

    common = {
        'MappedCRS': crs_name,
        'MappedScale': '1:100000',
        'ProjectID': project_id,
    }

    target, out_layers = create_output(out_path, srs)
    basemap = out_layers[BASEMAP_LAYER]
    linework = out_layers[LINEWORK_LAYER]

    counts = {'polygons': 0, 'lines': 0}
    unmapped = {'polygons': {}, 'lines': {}}
    how_counts = {}

    def note(how):
        how_counts[how] = how_counts.get(how, 0) + 1

    # ── polygons ────────────────────────────────────────────────────
    basemap.StartTransaction()
    for feature in poly_layer:
        code = (feature.GetField('CODE') or '').strip()
        row = poly_lut.get(code, {})
        lith1, lith2, prefix, mineral, texture, how = polygon_codes(code, row)
        note('poly:' + how)
        if lith1 is None:
            unmapped['polygons'][code] = unmapped['polygons'].get(code, 0) + 1
            continue
        values = dict(common)
        values.update({
            'Lithology1': lith1,
            'Lithology2': lith2,
            'LithologyPrefix': prefix,
            'Lith1Mineral1': mineral,
            'Lith1Texture1': texture,
            'MappedLithology1': (row.get('LITHNAME1') or '').strip() or None,
            'Comments': comment_for(code, row),
            'ContactType': 'Solid',
            'UUID': stable_uuid(sheet, 'basemap', feature.GetFID()),
        })
        write(basemap, feature.GetGeometryRef(), values)
        counts['polygons'] += 1
    basemap.CommitTransaction()

    # ── faults and fold axial traces ────────────────────────────────
    linework.StartTransaction()
    line_source, line_layer = open_layer(shapes, 'linear', sheet)
    if line_layer is not None:
        for feature in line_layer:
            feature_name = feature.GetField('FEATURE')
            type_name = feature.GetField('TYPE')
            code, confidence, weight, how = line_codes(feature_name, type_name)
            note('line:' + how)
            if code is None:
                key = '{0} / {1}'.format(feature_name, type_name)
                unmapped['lines'][key] = unmapped['lines'].get(key, 0) + 1
                continue
            values = dict(common)
            values.update({
                'Type': code,
                'Confidence': confidence,
                'Weight': weight,
                'Comments': '{0} | {1}'.format(feature_name, type_name),
                'UUID': stable_uuid(sheet, 'linear', feature.GetFID()),
            })
            write(linework, feature.GetGeometryRef(), values)
            counts['lines'] += 1

    # ── dykes ───────────────────────────────────────────────────────
    dyke_source, dyke_layer = open_layer(shapes, 'dyke', sheet)
    if dyke_layer is not None:
        for feature in dyke_layer:
            code = (feature.GetField('CODE') or '').strip()
            row = dyke_lut.get(code, {})
            target_code, how = dyke_code(row)
            note('dyke:' + how)
            if target_code is None:
                unmapped['lines'][code] = unmapped['lines'].get(code, 0) + 1
                continue
            values = dict(common)
            values.update({
                'Type': target_code,
                'Confidence': 'Observed',
                'Weight': 'Moderate',
                'Label': (row.get('UNITNAME') or '').strip() or None,
                'Comments': comment_for(code, row),
                'UUID': stable_uuid(sheet, 'dyke', feature.GetFID()),
            })
            write(linework, feature.GetGeometryRef(), values)
            counts['lines'] += 1

    # ── cross-section line ──────────────────────────────────────────
    section_source, section_layer = open_layer(shapes, 'section_line', sheet)
    if section_layer is not None:
        for feature in section_layer:
            line_id = (feature.GetField('LINE_ID') or '').strip()
            label = line_id.split(';')[-1].strip() or None
            values = dict(common)
            values.update({
                'Type': 'Section Line',
                'Confidence': 'Observed',
                'Weight': 'Moderate',
                'Label': label,
                'Comments': (feature.GetField('FEATURE') or '').strip(),
                'UUID': stable_uuid(sheet, 'section', feature.GetFID()),
            })
            write(linework, feature.GetGeometryRef(), values)
            counts['lines'] += 1
            note('section:table')
    linework.CommitTransaction()

    target = None
    for handle in (poly_source, line_source, dyke_source, section_source):
        del handle

    return sheet, counts, unmapped, how_counts


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    root, out_path = argv[1], argv[2]
    project_id = argv[3] if len(argv) > 3 else None

    sheet, counts, unmapped, how_counts = build(root, out_path, project_id)

    print('GSWA sheet {0} -> {1}'.format(sheet, out_path))
    print('  {0} polygons -> "{1}"'.format(counts['polygons'], BASEMAP_LAYER))
    print('  {0} lines    -> "{1}"'.format(counts['lines'], LINEWORK_LAYER))
    for how in sorted(how_counts):
        print('    {0:<20} {1}'.format(how, how_counts[how]))

    stragglers = 0
    for kind in ('polygons', 'lines'):
        for key, count in sorted(unmapped[kind].items()):
            print('  UNMAPPED {0}: {1} ({2} features) - dropped'.format(
                kind, key, count))
            stragglers += count
    if stragglers:
        print('  {0} features had no LGS code and were left out. Add them to '
              'GSWA_POLY / GSWA_LINE.'.format(stragglers))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
