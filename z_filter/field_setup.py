"""
Elevation field injection for the Z filter.

Adds the manually-entered "Elevation" (double) attribute to the standard
mapping layers of projects created before the field existed in the template.
Provider-direct add (no edit buffer), same pattern as
script_adddata/reconcile/migrate.ensure_lgs_columns. GUI prompts live in the
panel/controller — this module only reports.
"""

import math

from qgis.core import Qgis, QgsFeatureRequest

from .expression import (ELEVATION_FIELD, Z_MAX_FIELD, Z_MIN_FIELD,
                         spec_field_names)

try:
    from ..hardcode_data.analysis import create_compatible_field
except ImportError:  # standalone / console use
    from hardcode_data.analysis import create_compatible_field

ELEVATION_ALIAS = "Elevation (m)"

# Aliases for the range-mode fields materialized from geometry Z.
SPEC_ALIASES = {ELEVATION_FIELD: ELEVATION_ALIAS,
                Z_MIN_FIELD: "Z min (m)", Z_MAX_FIELD: "Z max (m)"}

# changeAttributeValues batch size — keeps the provider write window short
# on cloud-synced geopackages.
_BATCH_SIZE = 2000


def has_elevation_field(layer):
    return layer is not None and layer.fields().indexOf(ELEVATION_FIELD) != -1


def layers_missing_elevation(layers):
    return [lyr for lyr in layers if lyr is not None and not has_elevation_field(lyr)]


def _has_unsaved_edits(layer):
    if not layer.isEditable():
        return False
    buf = layer.editBuffer()
    return bool(buf and buf.isModified())


def _uses_designer_form(layer):
    try:
        return layer.editFormConfig().layout() == Qgis.AttributeFormLayout.DragAndDrop
    except AttributeError:  # QGIS < 3.32 enum name
        return False


def ensure_elevation_fields(layers):
    """Add the Elevation field to every layer that lacks it.

    Thin aggregation over ensure_spec_fields (the single provider-direct
    add ladder). Returns a report dict:
        added:        layer names the field was added to
        skipped:      (layer name, reason) tuples — e.g. unsaved edits
        errors:       (layer name, message) tuples
        custom_form:  layer names using a drag-and-drop designer form, where
                      the new field must be added to the form manually
    """
    report = {'added': [], 'skipped': [], 'errors': [], 'custom_form': []}
    spec = {'mode': 'single', 'field': ELEVATION_FIELD}
    for layer in layers:
        if layer is None or has_elevation_field(layer):
            continue
        result = ensure_spec_fields(layer, spec)
        if result['skipped']:
            report['skipped'].append((layer.name(), result['skipped']))
        elif result['error']:
            report['errors'].append((layer.name(), result['error']))
        elif result['added']:
            report['added'].append(layer.name())
            if _uses_designer_form(layer):
                report['custom_form'].append(layer.name())
    return report


def ensure_spec_fields(layer, spec):
    """Add the spec's missing field(s) to one layer, provider-direct.

    Same guard ladder as ensure_elevation_fields. Returns a report dict:
        added:   field names created
        skipped: reason string when nothing could be done (or None)
        error:   message string on provider failure (or None)
    """
    report = {'added': [], 'skipped': None, 'error': None}
    fields = layer.fields()
    missing = [name for name in spec_field_names(spec)
               if fields.indexOf(name) == -1]
    if not missing:
        return report
    if _has_unsaved_edits(layer):
        report['skipped'] = 'unsaved edits — save first'
        return report
    if layer.isEditable():
        layer.commitChanges()
    provider = layer.dataProvider()
    if provider is None or not provider.addAttributes(
            [create_compatible_field(name, 'double') for name in missing]):
        report['error'] = 'provider refused to add field(s)'
        return report
    layer.updateFields()
    for name in missing:
        idx = layer.fields().indexOf(name)
        if idx == -1:
            # Provider mangled the name (e.g. shapefile truncation).
            report['error'] = f'field "{name}" missing after add'
            return report
        alias = SPEC_ALIASES.get(name)
        if alias:
            layer.setFieldAlias(idx, alias)
        report['added'].append(name)
    return report


def _feature_z_range(geometry):
    """(zmin, zmax) over the geometry's vertices, or None when no usable Z."""
    if geometry is None or geometry.isEmpty():
        return None
    zmin = zmax = None
    try:
        vertices = geometry.vertices()
    except AttributeError:
        return None
    for vertex in vertices:
        z = vertex.z()
        if z != z:  # NaN — vertex has no Z
            continue
        if zmin is None or z < zmin:
            zmin = z
        if zmax is None or z > zmax:
            zmax = z
    if zmin is None:
        return None
    return (zmin, zmax)


def populate_z_from_geometry(layer, spec, only_null=True):
    """Fill the spec field(s) from geometry Z, provider-direct in batches.

    Points get the vertex Z; lines/polygons get min & max over all vertices
    (equal for flat strings, a real range for ramps). only_null skips rows
    already populated (range mode: only when BOTH fields hold values), so
    re-runs are cheap no-ops and partially-populated imports self-heal.

    Returns {'updated', 'failed', 'skipped_has_value', 'skipped_no_z',
    'total'} — 'failed' counts features whose provider write was refused.
    """
    is_range = spec.get('mode') == 'range'
    names = spec_field_names(spec)
    indexes = [layer.fields().indexOf(name) for name in names]
    report = {'updated': 0, 'failed': 0, 'skipped_has_value': 0,
              'skipped_no_z': 0, 'total': 0}
    if -1 in indexes:
        return report
    provider = layer.dataProvider()
    request = QgsFeatureRequest()
    request.setSubsetOfAttributes(indexes)
    batch = {}
    for feature in layer.getFeatures(request):
        report['total'] += 1
        if only_null and not any(
                _is_blank(feature.attribute(idx)) for idx in indexes):
            report['skipped_has_value'] += 1
            continue
        z_range = _feature_z_range(feature.geometry())
        if z_range is None:
            report['skipped_no_z'] += 1
            continue
        if is_range:
            batch[feature.id()] = {indexes[0]: z_range[0],
                                   indexes[1]: z_range[1]}
        else:
            batch[feature.id()] = {indexes[0]: z_range[0]}
        if len(batch) >= _BATCH_SIZE:
            if provider.changeAttributeValues(batch):
                report['updated'] += len(batch)
            else:
                report['failed'] += len(batch)
            batch = {}
    if batch:
        if provider.changeAttributeValues(batch):
            report['updated'] += len(batch)
        else:
            report['failed'] += len(batch)
    if report['updated']:
        # The subset filter evaluates provider-side — make sure the layer
        # sees the new values before a clause references them.
        layer.reload()
        layer.triggerRepaint()
    return report


def _is_blank(value):
    """NULL / non-numeric attribute value (mirrors the scan's blank rule)."""
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return True
