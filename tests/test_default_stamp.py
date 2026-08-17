"""
Unit tests for qfield_export/core/default_stamp.py (pure python).

Run from the plugin root:
    python -m unittest discover tests
"""

import importlib.util
import os
import unittest
import xml.etree.ElementTree as ET

# Load the module directly — importing the qfield_export package would
# pull in qgis (default_stamp itself is qgis-free by design).
_path = os.path.join(os.path.dirname(__file__), '..',
                     'qfield_export', 'core', 'default_stamp.py')
_spec = importlib.util.spec_from_file_location('default_stamp', _path)
default_stamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(default_stamp)

stamp_elevation_defaults = default_stamp.stamp_elevation_defaults
ELEVATION_DEFAULT_EXPRESSION = default_stamp.ELEVATION_DEFAULT_EXPRESSION

CANONICAL = ['1 - FieldNotebook', '2 - Linework', '3 - Overlay',
             '4 - Basemap']


def _project(*maplayers):
    return ET.fromstring(
        '<qgis version="3.40"><projectlayers>%s</projectlayers></qgis>'
        % ''.join(maplayers))


def _maplayer(name, body=''):
    return '<maplayer><layername>%s</layername>%s</maplayer>' % (name, body)


def _default_el(root, layer_name, field):
    for maplayer in root.iter('maplayer'):
        name_el = maplayer.find('layername')
        if name_el is not None and name_el.text == layer_name:
            defaults = maplayer.find('defaults')
            if defaults is None:
                return None
            for el in defaults.findall('default'):
                if el.get('field') == field:
                    return el
    return None


class TestStampElevationDefaults(unittest.TestCase):

    def test_expression_tripwire(self):
        # The sidecar writes lgs_z_* as STRING variables; the expression
        # must compare against '1' and cast with to_real. If this changes,
        # re-verify on-device behaviour before shipping.
        self.assertEqual(
            ELEVATION_DEFAULT_EXPRESSION,
            "if(@lgs_z_enabled = '1', to_real(@lgs_z_level), NULL)")

    def test_stamps_canonical_layers(self):
        root = _project(*[_maplayer(n) for n in CANONICAL])
        stamped = stamp_elevation_defaults(
            root, [(n, 'Elevation') for n in CANONICAL])
        self.assertEqual(stamped, CANONICAL)
        for name in CANONICAL:
            el = _default_el(root, name, 'Elevation')
            self.assertIsNotNone(el, name)
            self.assertEqual(el.get('expression'),
                             ELEVATION_DEFAULT_EXPRESSION)
            self.assertEqual(el.get('applyOnUpdate'), '0')

    def test_creates_missing_defaults_element(self):
        root = _project(_maplayer('1 - FieldNotebook'))
        stamp_elevation_defaults(root, [('1 - FieldNotebook', 'Elevation')])
        maplayer = next(root.iter('maplayer'))
        self.assertIsNotNone(maplayer.find('defaults'))

    def test_fills_existing_empty_default(self):
        body = ('<defaults>'
                '<default field="Elevation" expression="" applyOnUpdate="0"/>'
                '<default field="Other" expression="1+1"/>'
                '</defaults>')
        root = _project(_maplayer('3 - Overlay', body))
        stamped = stamp_elevation_defaults(root, [('3 - Overlay',
                                                   'Elevation')])
        self.assertEqual(stamped, ['3 - Overlay'])
        el = _default_el(root, '3 - Overlay', 'Elevation')
        self.assertEqual(el.get('expression'), ELEVATION_DEFAULT_EXPRESSION)
        # Unrelated field untouched.
        other = _default_el(root, '3 - Overlay', 'Other')
        self.assertEqual(other.get('expression'), '1+1')

    def test_skips_existing_nonempty_expression(self):
        body = ('<defaults>'
                '<default field="Elevation" expression="@my_custom"/>'
                '</defaults>')
        root = _project(_maplayer('2 - Linework', body))
        stamped = stamp_elevation_defaults(root, [('2 - Linework',
                                                   'Elevation')])
        self.assertEqual(stamped, [])
        el = _default_el(root, '2 - Linework', 'Elevation')
        self.assertEqual(el.get('expression'), '@my_custom')

    def test_stamps_extra_layer_custom_field(self):
        root = _project(_maplayer('Pit Design'))
        stamped = stamp_elevation_defaults(root, [('Pit Design', 'RL')])
        self.assertEqual(stamped, ['Pit Design'])
        el = _default_el(root, 'Pit Design', 'RL')
        self.assertEqual(el.get('expression'), ELEVATION_DEFAULT_EXPRESSION)

    def test_ignores_unmatched_and_unnamed_layers(self):
        root = _project(_maplayer('Some Other Layer'),
                        '<maplayer><id>no-name</id></maplayer>')
        stamped = stamp_elevation_defaults(
            root, [('1 - FieldNotebook', 'Elevation')])
        self.assertEqual(stamped, [])
        self.assertIsNone(_default_el(root, 'Some Other Layer', 'Elevation'))


if __name__ == '__main__':
    unittest.main()
