"""
Transported-cover opacity control for the Basemap layer.

A four-step ladder, 100 / 50 / 25 / Hidden:

* Hidden AND-s a subset-string clause onto "4 - Basemap", so features AND
  labels disappear (unlike renderer-category toggling). The clause always
  lives in the baseline subset, beneath any z-filter clause, so the z
  filter's stored-original bookkeeping and the QField exporter's strip
  both keep working unchanged.
* 100/50/25 fade instead, through a data-defined symbol opacity written
  onto every class symbol of the Basemap renderer; it reads the project
  variable @lgs_cover_opacity, so changing the level is one variable
  write. Labels keep drawing at full strength on a faded cover - only
  Hidden takes them away.

Both the renderer and the variable travel into QField exports verbatim,
so the device sidecar drives the same ladder by rewriting the variable.
Semantics mirrored in z_filter/qfield/lgs_companion.qml.
"""

from qgis.core import (QgsExpressionContextUtils, QgsProject, QgsProperty,
                       QgsSymbol)

from .z_filter.expression import (
    COVER_FIELD,
    COVER_STEPS,
    ENTRY_ORIG_SUBSET_PREFIX,
    SCOPE,
    VAR_COVER_HIDDEN,
    VAR_COVER_OPACITY,
    apply_cover_to_subset,
    combine,
    cover_opacity_expression,
    strip_cover_subset,
    strip_z_subset_any,
)
from . import renderer_compat
from .lgs_layers import BASEMAP, find_layer

BASEMAP_NAME = BASEMAP

# QGIS 4 scopes the symbol property enum; 3.x keeps it flat.
try:
    _PROP_OPACITY = QgsSymbol.Property.Opacity
except AttributeError:  # QGIS 3.x
    _PROP_OPACITY = QgsSymbol.PropertyOpacity


def get_basemap_layer(project=None):
    # find_layer rather than mapLayersByName: tolerates the pre-Aug-2026
    # numbering so older projects still resolve.
    return find_layer(project or QgsProject.instance(), BASEMAP)


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


def ensure_cover_opacity_dd(layer):
    """Bake the data-defined cover opacity onto every class symbol.

    Idempotent: the expression is a constant, so re-running overwrites
    with the same thing. Runs against the LIVE renderer rather than the
    shipped template, because existing projects were styled before this
    tool existed and the export copies whatever the project holds.

    Returns True when the property was written.
    """
    if layer is None:
        return False
    renderer = layer.renderer()
    if renderer is None or not renderer_compat.is_supported(renderer):
        return False
    clone = renderer.clone()
    prop = QgsProperty.fromExpression(cover_opacity_expression())
    written = 0
    for _value, symbol in renderer_compat.renderer_classes(clone):
        if symbol is None:
            continue
        try:
            symbol.setDataDefinedProperty(_PROP_OPACITY, prop)
            written += 1
        except (AttributeError, TypeError):
            continue
    if not written:
        return False
    layer.setRenderer(clone)
    layer.triggerRepaint()
    return True


def get_cover_opacity(project=None):
    """Current step: 0 when hidden, else the percent (default 100)."""
    project = project or QgsProject.instance()
    if is_cover_hidden(project):
        return 0
    raw = QgsExpressionContextUtils.projectScope(project).variable(
        VAR_COVER_OPACITY)
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return 100
    return value if value in COVER_STEPS and value else 100


def set_cover_opacity(iface, percent):
    """Apply one rung of the ladder. Returns success.

    0 delegates to the subset-string hide; anything else lifts that hide
    (quietly) and fades through the data-defined opacity instead.
    """
    if not percent:
        return set_cover_hidden(iface, True)
    project = QgsProject.instance()
    layer = get_basemap_layer(project)
    if layer is None:
        iface.messageBar().pushWarning(
            'Transported Cover',
            'Layer "%s" not found in this project.' % BASEMAP_NAME)
        return False
    if is_cover_hidden(project) and not set_cover_hidden(iface, False,
                                                         quiet=True):
        return False
    if not ensure_cover_opacity_dd(layer):
        iface.messageBar().pushWarning(
            'Transported Cover',
            'Could not set a data-defined opacity on "%s" — its symbology '
            'is not a categorized or rule-based renderer.' % BASEMAP_NAME)
        return False
    QgsExpressionContextUtils.setProjectVariable(
        project, VAR_COVER_OPACITY, str(int(percent)))
    layer.triggerRepaint()
    iface.messageBar().pushInfo(
        'Transported Cover', 'Transported cover at %d%%.' % int(percent))
    return True


def set_cover_hidden(iface, hidden, quiet=False):
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
    if not quiet:
        bar.pushInfo('Transported Cover',
                     'Transported cover hidden.' if hidden
                     else 'Transported cover visible.')
    return True
