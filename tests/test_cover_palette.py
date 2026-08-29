"""The Transported Cover register: the palette's own rules, and the template.

Two halves. The first checks scripts/cover_palette.py against itself and
against the resolved fills in Template/patterns/lith_fills.tsv - the same
gates inject_basemap_lith_patterns.py enforces, run without QGIS so a
palette edit is caught by the ordinary test run. The second reads the live
template's QML directly (sqlite3 only) and checks that what was injected is
still what the palette says: fills, contact tints, the untouched ContactType
mechanism, and the cover label token.
"""
import csv
import importlib.util
import os
import re
import sqlite3
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GPKG = os.path.join(REPO, "Template", "LGS_MappingTemplate.gpkg")
FILLS = os.path.join(REPO, "Template", "patterns", "lith_fills.tsv")
TEXTURES = os.path.join(REPO, "Template", "patterns", "lith_textures.tsv")
LAYER = "4 - Basemap"

_spec = importlib.util.spec_from_file_location(
    "cover_palette", os.path.join(REPO, "scripts", "cover_palette.py"))
cover_palette = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cover_palette)


def _rows(path):
    with open(path, encoding="utf-8") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if row and not row[0].startswith("#") and row[0] != "code":
                yield row


def _hex_to_rgb(text):
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def resolved_fills():
    return {row[0]: _hex_to_rgb(row[1]) for row in _rows(FILLS)}


def texture_tiles():
    return {row[0]: row[1] for row in _rows(TEXTURES)}


class TestPaletteShape(unittest.TestCase):

    def test_thirty_four_codes(self):
        self.assertEqual(len(cover_palette.COVER), 34)

    def test_thirteen_new_codes_are_in_the_palette(self):
        self.assertEqual(len(cover_palette.NEW_CODES), 13)
        for code, source in cover_palette.NEW_CODES:
            self.assertIn(code, cover_palette.COVER, code)
            self.assertIn(source, cover_palette.COVER, source)
            # A code cannot be cloned from one of its own round-2 siblings:
            # the source has to exist in the template already.
            self.assertNotIn(source, [c for c, _s in cover_palette.NEW_CODES],
                             "%s clones %s, which round 2 also adds"
                             % (code, source))

    def test_round1_codes_are_the_other_twenty_one(self):
        new = {c for c, _s in cover_palette.NEW_CODES}
        self.assertEqual(set(cover_palette.ROUND1_GREY),
                         set(cover_palette.COVER) - new)

    def test_every_code_has_a_family_with_a_contact_ink(self):
        for code in cover_palette.COVER:
            self.assertIn(cover_palette.family_of(code),
                          cover_palette.FAMILY_CONTACT, code)

    def test_every_family_is_used(self):
        used = {cover_palette.family_of(c) for c in cover_palette.COVER}
        self.assertEqual(used, set(cover_palette.FAMILY_CONTACT))


class TestPaletteRules(unittest.TestCase):
    """audit() is the palette's own contract; run it both ways."""

    def test_cover_only(self):
        self.assertEqual(cover_palette.audit(), [])

    def test_against_the_resolved_bedrock_fills(self):
        fills, tiles = resolved_fills(), texture_tiles()
        bedrock_fills = {c: v for c, v in fills.items()
                         if c not in cover_palette.COVER}
        bedrock_tiles = {c: v for c, v in tiles.items()
                         if c not in cover_palette.COVER}
        self.assertEqual(
            cover_palette.audit(bedrock_fills, bedrock_tiles), [])

    def test_the_ladder_stays_pale(self):
        # Cover is a veil the bedrock shows through: a mechanism hue must
        # not become a mechanism COLOUR. L* 65 is the floor.
        for code in cover_palette.COVER:
            lightness = cover_palette._lab(cover_palette.fill_of(code))[0]
            self.assertGreater(lightness, 65.0,
                               "%s at L* %.1f" % (code, lightness))

    def test_label_token_reads_on_every_cover_fill(self):
        # Round 4 dropped this floor from 2.0: the amber label is carried
        # by chroma on the near-neutral cream fills (the Ora Banda
        # precedent), so the floor only guards the truly illegible.
        for code in cover_palette.COVER:
            ratio = cover_palette.contrast_ratio(
                cover_palette.LABEL_TOKEN, cover_palette.fill_of(code))
            self.assertGreater(ratio, 1.8, "%s at %.2f:1" % (code, ratio))

    def test_label_token_is_not_the_bedrock_colour(self):
        self.assertGreater(
            cover_palette.contrast_ratio(cover_palette.LABEL_TOKEN,
                                         cover_palette.LABEL_BEDROCK), 2.5)

    def test_texture_map_agrees_with_the_palette(self):
        tiles = texture_tiles()
        for code in cover_palette.COVER:
            self.assertEqual(tiles.get(code), cover_palette.tile_of(code),
                             code)


@unittest.skipUnless(os.path.exists(GPKG), "template not present")
class TestTemplateMatchesPalette(unittest.TestCase):
    """What was injected is still what the palette says."""

    RGBA = re.compile(r'color_rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,'
                      r'\s*(\d+)\s*\)')

    @classmethod
    def setUpClass(cls):
        con = sqlite3.connect("file:%s?mode=ro" % GPKG.replace("\\", "/"),
                              uri=True)
        cls.qml, cls.sld = con.execute(
            "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
            (LAYER,)).fetchone()
        cls.codes = dict(con.execute(
            "SELECT Code, Type FROM BasemapCodes"))
        con.close()

    def symbol_block(self, code):
        cat = re.search(r'<category[^>]*value="%s"[^>]*/>' % code, self.qml)
        self.assertIsNotNone(cat, code)
        name = re.search(r'symbol="(\d+)"', cat.group(0)).group(1)
        m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % name, self.qml)
        depth = 0
        for t in re.finditer(r'<symbol\b|</symbol>', self.qml[m.start():]):
            depth += 1 if t.group(0) == '<symbol' else -1
            if depth == 0:
                return self.qml[m.start():m.start() + t.end()]
        self.fail("unbalanced symbol for %s" % code)

    def test_the_table_holds_exactly_the_palette_s_cover_codes(self):
        cover = {c for c, t in self.codes.items()
                 if t == "Transported Cover"}
        self.assertEqual(cover, set(cover_palette.COVER))

    def test_fills_and_contacts(self):
        for code in sorted(cover_palette.COVER):
            block = self.symbol_block(code)
            fill = re.search(r'<Option name="color" type="QString" '
                             r'value="(\d+),(\d+),(\d+)', block)
            line = re.search(r'<Option name="line_color" type="QString" '
                             r'value="(\d+),(\d+),(\d+)', block)
            self.assertEqual(tuple(int(x) for x in fill.groups()),
                             cover_palette.fill_of(code), code)
            self.assertEqual(tuple(int(x) for x in line.groups()),
                             cover_palette.contact_of(code), code)

    def test_contacttype_mechanism_survives_the_tint(self):
        # Only the RGB moved: both branches still there, alpha still 0 for
        # 'None' and 255 otherwise, still switching on ContactType.
        for code in sorted(cover_palette.COVER):
            block = self.symbol_block(code)
            key = block.find('<Option name="outlineColor" type="Map">')
            self.assertGreater(key, 0, code)
            expr = re.compile(r'<Option name="expression" type="QString" '
                              r'value="([^"]*)"').search(block, key).group(1)
            found = self.RGBA.findall(expr)
            self.assertEqual([a for *_rgb, a in found], ["0", "255"], code)
            self.assertEqual({tuple(int(x) for x in rgb)
                              for *rgb, _a in found},
                             {cover_palette.contact_of(code)}, code)
            self.assertIn("ContactType", expr, code)

    def test_bedrock_keeps_the_near_black_contact(self):
        for code in ("SST", "RCC", "SSL", "MG"):
            block = self.symbol_block(code)
            key = block.find('<Option name="outlineColor" type="Map">')
            expr = re.compile(r'<Option name="expression" type="QString" '
                              r'value="([^"]*)"').search(block, key).group(1)
            self.assertEqual({tuple(int(x) for x in rgb)
                              for *rgb, _a in self.RGBA.findall(expr)},
                             {cover_palette.CONTACT_BEDROCK}, code)

    def test_sld_mirrors_the_qml(self):
        for code in sorted(cover_palette.COVER):
            rule = None
            for m in re.finditer(r'<se:Rule>.*?</se:Rule>', self.sld, re.S):
                if "<ogc:Literal>%s</ogc:Literal>" % code in m.group(0):
                    rule = m.group(0)
                    break
            self.assertIsNotNone(rule, code)
            self.assertEqual(
                re.findall(r'name="fill">(#[0-9a-fA-F]{6})', rule),
                [cover_palette.rgb_hex(cover_palette.fill_of(code))], code)
            self.assertEqual(
                re.findall(r'name="stroke">(#[0-9a-fA-F]{6})', rule),
                [cover_palette.rgb_hex(cover_palette.contact_of(code))], code)

    def test_label_token_is_data_defined_on_typelith1(self):
        # It has to be QgsPalLayerSettings' dd_properties - the block after
        # </text-style>. The text-style's own belongs to QgsTextFormat and
        # is never consulted while a label is drawn: a Color written there
        # parses, round-trips, and loads back inactive.
        style = re.search(r'<text-style\b.*?</text-style>', self.qml,
                          re.S)
        labeling = re.search(r'<labeling.*?</labeling>', self.qml, re.S)
        dd = re.compile(r'<dd_properties>.*?</dd_properties>', re.S).search(
            self.qml, style.end(), labeling.end()).group(0)
        self.assertIn('name="Color"', dd)
        self.assertIn(cover_palette.rgb_hex(cover_palette.LABEL_TOKEN), dd)
        self.assertIn(cover_palette.rgb_hex(cover_palette.LABEL_BEDROCK), dd)
        self.assertIn("TypeLith1", dd.replace("&quot;", '"'))
        self.assertNotIn('name="Color"', style.group(0),
                         "an inactive Color property is in the text-style")
        # The static colour still belongs to inject_label_cartography.py.
        self.assertIn('textColor="26,26,26,255', style.group(0))

    def test_cover_labels_are_a_size_step_up(self):
        # Round 3's second identity channel: the dd Size expression
        # (inject_label_size_scaling.py) scales Transported Cover labels
        # by 6.5/5.5 over the lithology base. Pin the branch, not the
        # whole expression - the extent factor is that script's business.
        style = re.search(r'<text-style\b.*?</text-style>', self.qml, re.S)
        labeling = re.search(r'<labeling.*?</labeling>', self.qml, re.S)
        dd = re.compile(r'<dd_properties>.*?</dd_properties>', re.S).search(
            self.qml, style.end(), labeling.end()).group(0)
        size = re.search(r'<Option name="Size" type="Map">.*?'
                         r'name="expression" type="QString" value="([^"]*)"',
                         dd, re.S)
        self.assertIsNotNone(size, "no dd Size on the Basemap labeling")
        expr = size.group(1).replace("&quot;", '"')
        self.assertIn("\"TypeLith1\" = 'Transported Cover'", expr)
        self.assertIn("6.5 / 5.5", expr)


if __name__ == "__main__":
    unittest.main()
