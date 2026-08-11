"""
QGIS adapter for extra-layer auto-detection.

Reads fields / geometry / provider capabilities off real layers and feeds
them to the pure-python heuristics in z_filter/detect.py. Kept thin so the
decision logic stays unit-testable without qgis.
"""

from qgis.core import Qgis, QgsProject, QgsWkbTypes

from . import detect
from .expression import Z_LAYERS, spec_field_names


def _geometry_class(layer):
    return {
        Qgis.GeometryType.Point: 'point',
        Qgis.GeometryType.Line: 'line',
        Qgis.GeometryType.Polygon: 'polygon',
    }.get(layer.geometryType())


def _provider_writable(provider):
    """Can the provider add fields and change attribute values?"""
    if provider is None:
        return False
    caps = provider.capabilities()
    try:
        add = Qgis.VectorProviderCapability.AddAttributes
        change = Qgis.VectorProviderCapability.ChangeAttributeValues
    except AttributeError:  # QGIS < 3.40 enum home
        from qgis.core import QgsVectorDataProvider
        add = QgsVectorDataProvider.AddAttributes
        change = QgsVectorDataProvider.ChangeAttributeValues
    return bool(caps & add) and bool(caps & change)


def detect_extra_layers(project=None, exclude_ids=()):
    """All eligible non-canonical vector layers, sorted by name.

    exclude_ids: layer ids already claimed by the panel's slot combos.
    Returns rows [{'layer': QgsVectorLayer,
                   'spec': best candidate (mutated by merge_with_persisted),
                   'specs': all candidates, best first,
                   'checked': bool}].
    """
    project = project or QgsProject.instance()
    exclude = set(exclude_ids)
    rows = []
    for layer in project.mapLayers().values():
        if layer.type() != Qgis.LayerType.Vector:
            continue
        if layer.id() in exclude or layer.name() in Z_LAYERS:
            continue
        if layer.providerType() == 'memory':
            continue  # won't survive a QField export
        geometry_class = _geometry_class(layer)
        if geometry_class is None:
            continue
        numeric_fields = [f.name() for f in layer.fields() if f.isNumeric()]
        specs = detect.candidate_specs(
            layer.name(), numeric_fields,
            QgsWkbTypes.hasZ(layer.wkbType()), geometry_class,
            _provider_writable(layer.dataProvider()))
        if specs:
            spec = specs[0]
            rows.append({
                'layer': layer, 'spec': spec, 'specs': specs,
                'checked': spec['auto_check'] and not spec['disabled_reason'],
            })
    rows.sort(key=lambda row: row['layer'].name().lower())
    return rows


def merge_with_persisted(detected, persisted_entries):
    """Overlay persisted user choices onto freshly detected rows.

    Persisted 'checked' and source choice win by layer id; rows without a
    persisted entry keep their detection default. Persisted entries whose
    layer id vanished drop out by construction — only detected rows return.
    """
    by_id = {e['id']: e for e in persisted_entries if e.get('id')}
    for row in detected:
        entry = by_id.get(row['layer'].id())
        if entry is None:
            continue
        # Re-select the candidate the user chose, provided it still exists.
        entry_fields = spec_field_names(entry)
        for candidate in row['specs']:
            if (candidate['mode'] == entry['mode']
                    and spec_field_names(candidate) == entry_fields):
                row['spec'] = candidate
                break
        row['checked'] = bool(entry['checked']) and \
            not row['spec']['disabled_reason']
    return detected


def to_persist_entries(rows):
    """Serialize detected rows (post-merge) for expression.format_extra_layers."""
    entries = []
    for row in rows:
        spec = row['spec']
        entry = {
            'id': row['layer'].id(),
            'name': row['layer'].name(),
            'mode': spec['mode'],
            'source': spec['source'],
            'checked': bool(row['checked']),
        }
        if spec['mode'] == 'range':
            entry['field_min'] = spec['field_min']
            entry['field_max'] = spec['field_max']
        else:
            entry['field'] = spec['field']
        entries.append(entry)
    return entries
