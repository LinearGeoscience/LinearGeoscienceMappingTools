"""
Reading values out of the source, whatever the source is.

Two backends behind one shape: a GeoPackage table read with sqlite3 (pure, and
fast enough to count a 2000-feature column without opening QGIS) and a loaded
QgsVectorLayer, which is what the database-subset workflow needs because the
layer's own subset filter and selection are the whole point of it.
"""

import sqlite3
from collections import OrderedDict

try:
    from .domain import is_blank, normalise
except ImportError:  # flat execution / pure test loader
    from domain import is_blank, normalise


# Above this many distinct values a column is free text, not a code list, and
# enumerating it helps nobody.
DISTINCT_CAP = 2000


class ValueCounts(object):
    """Distinct non-empty values of one column, with feature counts."""

    __slots__ = ('field', 'counts', 'total', 'empty', 'truncated')

    def __init__(self, field, counts=None, total=0, empty=0, truncated=False):
        self.field = field
        self.counts = counts or OrderedDict()
        self.total = total
        self.empty = empty
        self.truncated = truncated

    @property
    def distinct(self):
        return len(self.counts)

    def most_common(self):
        return sorted(self.counts.items(), key=lambda pair: (-pair[1], pair[0]))

    def __repr__(self):
        return 'ValueCounts({0!r}, {1} distinct, {2} features)'.format(
            self.field, self.distinct, self.total)


def _connect(path):
    return sqlite3.connect('file:{0}?mode=ro'.format(path.replace('?', '%3f')),
                           uri=True)


def gpkg_value_counts(path, table, fields):
    """{field: ValueCounts} for several columns of a GeoPackage table."""
    results = OrderedDict()
    connection = _connect(path)
    try:
        quoted_table = table.replace('"', '""')
        try:
            total = connection.execute(
                'SELECT COUNT(*) FROM "{0}"'.format(quoted_table)).fetchone()[0]
        except sqlite3.Error:
            return results
        for field in fields:
            quoted = field.replace('"', '""')
            counts = OrderedDict()
            empty = 0
            truncated = False
            try:
                rows = connection.execute(
                    'SELECT "{0}", COUNT(*) FROM "{1}" GROUP BY 1 '
                    'ORDER BY COUNT(*) DESC'.format(quoted, quoted_table))
            except sqlite3.Error:
                continue
            for raw, count in rows:
                if is_blank(raw):
                    empty += count
                    continue
                value = normalise(raw)
                if len(counts) >= DISTINCT_CAP:
                    truncated = True
                    continue
                counts[value] = counts.get(value, 0) + count
            results[field] = ValueCounts(field, counts, total, empty, truncated)
        return results
    finally:
        connection.close()


def layer_value_counts(layer, fields, selected_only=False):
    """{field: ValueCounts} for a loaded QgsVectorLayer.

    Honours the layer's subset filter automatically (getFeatures respects it)
    and, when asked, restricts to the current selection — that pair is what
    makes "import the filtered subset I am looking at" work.
    """
    from qgis.core import Qgis, QgsFeatureRequest

    indexes = []
    for field in fields:
        index = layer.fields().lookupField(field)
        if index >= 0:
            indexes.append((field, index))
    if not indexes:
        return OrderedDict()

    request = QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry)
    request.setSubsetOfAttributes([index for _name, index in indexes])
    if selected_only:
        request.setFilterFids(layer.selectedFeatureIds())

    results = OrderedDict(
        (name, ValueCounts(name)) for name, _index in indexes)
    total = 0
    for feature in layer.getFeatures(request):
        total += 1
        for name, index in indexes:
            bucket = results[name]
            raw = feature[index]
            if is_blank(raw):
                bucket.empty += 1
                continue
            value = normalise(raw)
            if value not in bucket.counts and len(bucket.counts) >= DISTINCT_CAP:
                bucket.truncated = True
                continue
            bucket.counts[value] = bucket.counts.get(value, 0) + 1
    for bucket in results.values():
        bucket.total = total
    return results


def feature_source_value_counts(feature_source, field_names, fields,
                                fids=None):
    """Same counts, from a QgsVectorLayerFeatureSource captured earlier.

    A layer loaded in QGIS cannot be read off the main thread, but the feature
    source snapshot taken from it can — so counting the values of a filtered
    PostGIS layer happens on the worker like everything else, instead of
    freezing QGIS while it runs.
    """
    from qgis.core import Qgis, QgsFeatureRequest

    indexes = [(name, field_names.index(name))
               for name in fields if name in field_names]
    if not indexes:
        return OrderedDict()

    request = QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry)
    request.setSubsetOfAttributes([index for _name, index in indexes])
    if fids is not None:
        request.setFilterFids(list(fids))

    results = OrderedDict((name, ValueCounts(name)) for name, _i in indexes)
    total = 0
    for feature in feature_source.getFeatures(request):
        total += 1
        values = feature.attributes()
        for name, index in indexes:
            bucket = results[name]
            raw = values[index] if index < len(values) else None
            if is_blank(raw):
                bucket.empty += 1
                continue
            value = normalise(raw)
            if value not in bucket.counts and len(bucket.counts) >= DISTINCT_CAP:
                bucket.truncated = True
                continue
            bucket.counts[value] = bucket.counts.get(value, 0) + 1
    for bucket in results.values():
        bucket.total = total
    return results


def gpkg_feature_count(path, table, where=''):
    connection = _connect(path)
    try:
        sql = 'SELECT COUNT(*) FROM "{0}"'.format(table.replace('"', '""'))
        if where:
            sql += ' WHERE ' + where
        return connection.execute(sql).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        connection.close()
