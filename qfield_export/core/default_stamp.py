"""
Export-time default-value stamping for the QField Z-filter workflow.

When the Z-filter sidecar ships with an export, newly digitized features
should inherit the active level as their Elevation. The exported .qgs is
mutated as raw XML (offline_converter never opens a QgsProject for the
copy), so this module writes a <default> expression onto the Elevation
field of each target layer:

    if(@lgs_z_enabled = '1', to_real(@lgs_z_level), NULL)

The sidecar maintains lgs_z_enabled / lgs_z_level as *string* project
variables at runtime, so the expression compares against '1' and casts
the level with to_real(). With the filter off (or the variables absent)
it evaluates to NULL — exactly the pre-existing behaviour.

Range-mode extra layers are never stamped: writing one level into both
min and max fields would fabricate flat features, which is wrong for the
ramps range mode exists to represent.

Pure python (xml.etree only, no qgis imports) so tests load it directly.
"""

import xml.etree.ElementTree as ET

ELEVATION_DEFAULT_EXPRESSION = (
    "if(@lgs_z_enabled = '1', to_real(@lgs_z_level), NULL)")


def stamp_elevation_defaults(root, targets):
    """Set the auto-stamp default expression on target layers' fields.

    root: ElementTree root of an exported .qgs document
    targets: iterable of (layer_name, field_name) pairs

    A field that already carries a non-empty default expression is left
    untouched (never wrap an expression we don't understand). Defaults
    apply on create only (applyOnUpdate="0") — editing an existing
    feature must not silently rewrite its elevation.

    Returns the list of layer names actually stamped.
    """
    wanted = {}
    for layer_name, field_name in targets:
        wanted.setdefault(layer_name, field_name)
    stamped = []
    for maplayer in root.iter('maplayer'):
        name_el = maplayer.find('layername')
        name = name_el.text if name_el is not None else None
        if name not in wanted:
            continue
        field_name = wanted[name]
        defaults = maplayer.find('defaults')
        if defaults is None:
            defaults = ET.SubElement(maplayer, 'defaults')
        default = None
        for el in defaults.findall('default'):
            if el.get('field') == field_name:
                default = el
                break
        if default is None:
            default = ET.SubElement(defaults, 'default')
            default.set('field', field_name)
            default.set('expression', '')
        if (default.get('expression') or '').strip():
            continue
        default.set('expression', ELEVATION_DEFAULT_EXPRESSION)
        default.set('applyOnUpdate', '0')
        stamped.append(name)
    return stamped
