"""
Elevation field injection for the Z filter.

Adds the manually-entered "Elevation" (double) attribute to the standard
mapping layers of projects created before the field existed in the template.
Provider-direct add (no edit buffer), same pattern as
script_adddata/reconcile/migrate.ensure_lgs_columns. GUI prompts live in the
panel/controller — this module only reports.
"""

from qgis.core import Qgis

from .expression import ELEVATION_FIELD

try:
    from ..hardcode_data.analysis import create_compatible_field
except ImportError:  # standalone / console use
    from hardcode_data.analysis import create_compatible_field

ELEVATION_ALIAS = "Elevation (m)"


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

    Returns a report dict:
        added:        layer names the field was added to
        skipped:      (layer name, reason) tuples — e.g. unsaved edits
        errors:       (layer name, message) tuples
        custom_form:  layer names using a drag-and-drop designer form, where
                      the new field must be added to the form manually
    """
    report = {'added': [], 'skipped': [], 'errors': [], 'custom_form': []}
    for layer in layers:
        if layer is None or has_elevation_field(layer):
            continue
        if _has_unsaved_edits(layer):
            report['skipped'].append((layer.name(), 'unsaved edits — save first'))
            continue
        if layer.isEditable():
            # Clean session left open; close it so the provider add sticks.
            layer.commitChanges()
        provider = layer.dataProvider()
        if provider is None or not provider.addAttributes(
                [create_compatible_field(ELEVATION_FIELD, 'double')]):
            report['errors'].append((layer.name(), 'provider refused to add field'))
            continue
        layer.updateFields()
        idx = layer.fields().indexOf(ELEVATION_FIELD)
        if idx != -1:
            layer.setFieldAlias(idx, ELEVATION_ALIAS)
            report['added'].append(layer.name())
            if _uses_designer_form(layer):
                report['custom_form'].append(layer.name())
        else:
            report['errors'].append((layer.name(), 'field missing after add'))
    return report
