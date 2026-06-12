"""
Legend builder utility functions.

Core logic for scanning fields across groups, collecting unique values,
and building rule-based renderers with hierarchical group rules.
Used by the Map Layout Generator for print legend expansion.
"""

from qgis.core import (
    QgsCategorizedSymbolRenderer, QgsRuleBasedRenderer,
    QgsSymbol,
)


def _is_valid_value(val):
    """Check if a field value is non-NULL and non-empty."""
    if val is None:
        return False
    s = str(val).strip()
    return bool(s) and s != 'NULL'


def scan_field_group(layer, field_names):
    """Collect unique non-NULL values across all fields in a group.

    Uses layer.uniqueValues() for performance.
    Returns a sorted list of unique string values.
    """
    unique = set()
    for fname in field_names:
        idx = layer.fields().indexOf(fname)
        if idx < 0:
            continue
        for val in layer.uniqueValues(idx):
            if _is_valid_value(val):
                unique.add(str(val))
    return sorted(unique)


def scan_field_group_subdivided(layer, field_names, subdivide_field):
    """Scan values grouped by a parent/type field.

    Iterates features to correlate each value with its parent type.
    Returns {subdivide_value: [sorted unique subtype values]}.
    """
    sub_idx = layer.fields().indexOf(subdivide_field)
    if sub_idx < 0:
        return {}

    field_indices = []
    for fn in field_names:
        fi = layer.fields().indexOf(fn)
        if fi >= 0:
            field_indices.append((fn, fi))

    if not field_indices:
        return {}

    grouped = {}  # {type_val: set(subtype_vals)}

    for feat in layer.getFeatures():
        type_val = feat[sub_idx]
        if not _is_valid_value(type_val):
            continue
        type_str = str(type_val)

        if type_str not in grouped:
            grouped[type_str] = set()

        for _fname, fidx in field_indices:
            val = feat[fidx]
            if _is_valid_value(val):
                grouped[type_str].add(str(val))

    return {k: sorted(v) for k, v in sorted(grouped.items())}


def preview_legend_groups(layer, field_groups):
    """Dry-run scan of field groups.

    field_groups: list of (group_name, [field_names], subdivide_by_or_None).
    Returns dict of {group_name: data} where data is either:
      - list[str] for flat groups (subdivide_by is None)
      - dict[str, list[str]] for subdivided groups
    """
    result = {}
    for group_name, field_names, subdivide_by in field_groups:
        if subdivide_by:
            result[group_name] = scan_field_group_subdivided(
                layer, field_names, subdivide_by)
        else:
            result[group_name] = scan_field_group(layer, field_names)
    return result


def build_grouped_renderer(layer, field_groups, existing_renderer,
                           include_catch_all=True):
    """Build a QgsRuleBasedRenderer with hierarchical group rules.

    Args:
        layer: QgsVectorLayer to build renderer for.
        field_groups: list of (group_name, [field_names], subdivide_by_or_None).
        existing_renderer: current renderer (to extract symbols from).
        include_catch_all: whether to add an else rule for unmatched features.

    Returns:
        QgsRuleBasedRenderer with nested group structure.
    """
    # Extract value -> symbol map from existing categorized renderer
    symbol_map = {}
    if isinstance(existing_renderer, QgsCategorizedSymbolRenderer):
        for cat in existing_renderer.categories():
            val = cat.value()
            if val is not None and str(val).strip():
                symbol_map[str(val)] = cat.symbol().clone()

    default_symbol = QgsSymbol.defaultSymbol(layer.geometryType())

    # Build rule tree
    root_rule = QgsRuleBasedRenderer.Rule(None)

    for group_name, field_names, subdivide_by in field_groups:
        if not field_names:
            continue

        # Parent group rule -- legend heading, no filter, no symbol
        group_rule = QgsRuleBasedRenderer.Rule(None)
        group_rule.setLabel(group_name)

        if subdivide_by:
            # Subdivided: create sub-groups by type value
            subdivided = scan_field_group_subdivided(
                layer, field_names, subdivide_by)

            for type_val, subtype_values in subdivided.items():
                sub_group = QgsRuleBasedRenderer.Rule(None)
                sub_group.setLabel(type_val)

                for val in subtype_values:
                    escaped_val = val.replace("'", "''")
                    escaped_type = type_val.replace("'", "''")

                    subtype_parts = [
                        f'"{fn}" = \'{escaped_val}\'' for fn in field_names]
                    filter_expr = (
                        f'"{subdivide_by}" = \'{escaped_type}\' AND '
                        f'({" OR ".join(subtype_parts)})')

                    symbol = symbol_map.get(val, default_symbol).clone()
                    child_rule = QgsRuleBasedRenderer.Rule(symbol)
                    child_rule.setFilterExpression(filter_expr)
                    child_rule.setLabel(val)
                    sub_group.appendChild(child_rule)

                group_rule.appendChild(sub_group)
        else:
            # Flat: scan unique values across all fields
            unique_values = scan_field_group(layer, field_names)

            for val in unique_values:
                escaped_val = val.replace("'", "''")
                parts = [
                    f'"{fname}" = \'{escaped_val}\'' for fname in field_names]
                filter_expr = " OR ".join(parts)

                symbol = symbol_map.get(val, default_symbol).clone()
                child_rule = QgsRuleBasedRenderer.Rule(symbol)
                child_rule.setFilterExpression(filter_expr)
                child_rule.setLabel(val)
                group_rule.appendChild(child_rule)

        root_rule.appendChild(group_rule)

    # Optional catch-all else rule for unmatched features
    if include_catch_all:
        else_rule = QgsRuleBasedRenderer.Rule(default_symbol.clone())
        else_rule.setIsElse(True)
        else_rule.setLabel("Other")
        root_rule.appendChild(else_rule)

    return QgsRuleBasedRenderer(root_rule)
