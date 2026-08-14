"""
Transported-cover visibility toggle for the Basemap layer.

Hides/shows every polygon whose primary type is 'Transported Cover' by
AND-ing a subset-string clause onto "4 - Basemap" (features AND labels
disappear, unlike renderer-category toggling). The clause always lives in
the baseline subset, beneath any z-filter clause, so the z filter's
stored-original bookkeeping and the QField exporter's strip both keep
working unchanged. Semantics mirrored in z_filter/qfield/lgs_companion.qml.
"""

from qgis.core import QgsExpressionContextUtils, QgsProject

from .z_filter.expression import (
    COVER_FIELD,
    ENTRY_ORIG_SUBSET_PREFIX,
    SCOPE,
    VAR_COVER_HIDDEN,
    Z_LAYERS,
    apply_cover_to_subset,
    combine,
    strip_cover_subset,
    strip_z_subset_any,
)

BASEMAP_NAME = Z_LAYERS[3]  # '4 - Basemap'


def get_basemap_layer(project=None):
    project = project or QgsProject.instance()
    matches = project.mapLayersByName(BASEMAP_NAME)
    return matches[0] if matches else None


def _split_live_subset(project, layer):
    """Split the live subset into (baseline, z_text, have_entry).

    baseline is the subset with any z-filter clause removed; z_text is the
    clause text to re-AND on top (None when no z filter owns the layer).
    Prefers the z controller's stored-original entry — apply_filter always
    sets the live subset to combine(stored, clause) — and falls back to
    strip_z_subset_any for a clause applied outside this session.
    """
    live = (layer.subsetString() or "").strip()
    key = ENTRY_ORIG_SUBSET_PREFIX + layer.id()
    stored, have_entry = project.readEntry(SCOPE, key, "")
    if have_entry:
        stored = (stored or "").strip()
        if live == stored:
            return stored, None, True
        if stored:
            prefix = '(%s) AND ' % stored
            if live.startswith(prefix):
                return stored, live[len(prefix):], True
        elif live:
            return "", live, True
    baseline = strip_z_subset_any(live)
    if baseline != live:
        if baseline:
            prefix = '(%s) AND ' % baseline
            if live.startswith(prefix):
                return baseline, live[len(prefix):], have_entry
        else:
            return "", live, have_entry
    return live, None, have_entry


def is_cover_hidden(project=None):
    """Whether the hide clause is currently active, derived from the live
    subset (no state flag to drift)."""
    project = project or QgsProject.instance()
    layer = get_basemap_layer(project)
    if layer is None:
        return False
    baseline, _, _ = _split_live_subset(project, layer)
    return strip_cover_subset(baseline) != baseline


def set_cover_hidden(iface, hidden):
    """Apply/remove the transported-cover hide clause. Returns success."""
    project = QgsProject.instance()
    bar = iface.messageBar()
    layer = get_basemap_layer(project)
    if layer is None:
        bar.pushWarning('Transported Cover',
                        'Layer "%s" not found in this project.' % BASEMAP_NAME)
        return False
    if layer.fields().indexOf(COVER_FIELD) == -1:
        bar.pushWarning('Transported Cover',
                        '"%s" has no "%s" field — template too old for this '
                        'tool.' % (BASEMAP_NAME, COVER_FIELD))
        return False
    if layer.isEditable():
        buf = layer.editBuffer()
        if buf and buf.isModified():
            bar.pushWarning('Transported Cover',
                            'Unsaved edits on "%s" — save them first.'
                            % BASEMAP_NAME)
            return False
        # Clean session left open; close it so the provider filter change
        # is safe (mirror of z_filter.controller.apply_filter).
        layer.commitChanges()

    baseline, z_text, have_entry = _split_live_subset(project, layer)
    new_baseline = apply_cover_to_subset(baseline, hidden)
    new_live = combine(new_baseline, z_text) if z_text else new_baseline
    previous = layer.subsetString()
    if not layer.setSubsetString(new_live):
        layer.setSubsetString(previous)
        bar.pushCritical('Transported Cover',
                         'Provider rejected the filter change.')
        return False
    if have_entry:
        # Keep the z filter's stored original in step so its clear/re-apply
        # preserves the cover state in both directions.
        project.writeEntry(SCOPE, ENTRY_ORIG_SUBSET_PREFIX + layer.id(),
                           new_baseline)
    layer.triggerRepaint()
    # Travels into QField exports so the device UI opens in the same state.
    QgsExpressionContextUtils.setProjectVariable(
        project, VAR_COVER_HIDDEN, '1' if hidden else '0')
    bar.pushInfo('Transported Cover',
                 'Transported cover hidden.' if hidden
                 else 'Transported cover visible.')
    return True
