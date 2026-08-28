"""Give Transported Cover labels their own colour, as a layer-identity token.

The old Ora Banda project's cleverest cheap trick: cover labels in gold,
bedrock labels in black, so you can read which register a polygon belongs to
from the TEXT ALONE, with no legend and no second look at the fill. The
lettering is otherwise identical - same font, same size, same grammar - so
this costs nothing in the label cartography and adds a whole channel.

Ours is one token for all cover (cover_palette.LABEL_TOKEN #6f6436, a deep
muted ochre), not a per-family colour: the fill already says WHICH cover,
the label only has to say THAT it is cover. See cover_palette for why the
token is this dark - the '4 - Basemap' labels draw with no buffer, so a
paler ochre is illegible on the darker cover fills.

MECHANICS
---------
A data-defined `Color` property switching on TypeLith1 - the same field the
cover-visibility toggle filters on, so the two always agree about what cover
is. The static textColor attribute is left exactly as it is: it stays the
bedrock colour, it is what inject_label_cartography.py owns and rewrites,
and the data-defined property overrides it per feature without either
script fighting the other.

WHICH dd_properties BLOCK - there are two, and only one works
------------------------------------------------------------
The labeling carries a <dd_properties> inside <text-style> (QgsTextFormat's
own) and another as a direct child of <settings> (QgsPalLayerSettings', the
one already holding LineAnchorClipping and friends). Label rendering
evaluates the SETTINGS one. Writing Color into the text-style block parses
fine, round-trips fine, survives every XML check - and loads back with
`isActive() == False`, i.e. silently does nothing. That was this script's
first version; the property must go in the settings block, and this one
removes a stray text-style Color if it finds the older mistake.

Idempotent: writes the property if the settings block has none, leaves it
alone if it already carries this expression, and aborts if something else
has claimed Color.

Usage:  python scripts/inject_cover_label_token.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cover_palette

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYER = "4 - Basemap"
COVER_TYPE = "Transported Cover"
FIELD = "TypeLith1"


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def expression():
    """The per-feature text colour. Hex literals, which QGIS accepts as a
    colour string for a data-defined Color property."""
    return ("CASE WHEN \"%s\" = '%s' THEN '%s' ELSE '%s' END"
            % (FIELD, COVER_TYPE,
               cover_palette.rgb_hex(cover_palette.LABEL_TOKEN),
               cover_palette.rgb_hex(cover_palette.LABEL_BEDROCK)))


def xml_attr(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def property_xml():
    return ('<Option name="Color" type="Map">'
            '<Option name="active" type="bool" value="true"/>'
            '<Option name="expression" type="QString" value="%s"/>'
            '<Option name="type" type="int" value="3"/>'
            '</Option>' % xml_attr(expression()))


def _labeling(qml):
    lab = re.search(r'<labeling.*?</labeling>', qml, re.S)
    if not lab:
        bail("no <labeling> block on %r" % LAYER)
    return lab


def _text_style_span(qml):
    lab = _labeling(qml)
    ts = re.search(r'<text-style\b.*?</text-style>', lab.group(0), re.S)
    if not ts:
        bail("no <text-style> block on %r" % LAYER)
    return lab.start() + ts.start(), lab.start() + ts.end(), ts.group(0)


def settings_dd(qml):
    """(start, end, text) of QgsPalLayerSettings' own <dd_properties>.

    The one the label renderer reads: a direct child of <settings>, which
    means the first <dd_properties> to appear AFTER </text-style> - the
    text-style's own block belongs to QgsTextFormat and is not consulted
    when a label is drawn.
    """
    _ts_start, ts_end, _ts = _text_style_span(qml)
    lab = _labeling(qml)
    dd = re.compile(r'<dd_properties>.*?</dd_properties>', re.S).search(
        qml, ts_end, lab.end())
    if not dd:
        bail("no settings-level <dd_properties> block after </text-style>")
    return dd.start(), dd.end(), dd.group(0)


def strip_text_style_color(qml):
    """Remove a Color property mistakenly written into the text-style block.

    The first version of this script put it there, where it parses and
    round-trips but loads back inactive. Returns (qml, removed?).
    """
    start, end, block = _text_style_span(qml)
    inner = re.search(r'<Option name="Color" type="Map">.*?'
                      r'<Option name="type" type="int" value="3"/>\s*</Option>',
                      block, re.S)
    if not inner:
        return qml, False
    cleaned = block[:inner.start()] + block[inner.end():]
    # An emptied properties Map goes back to the self-closing form QGIS
    # writes when there is nothing in it.
    cleaned = re.sub(r'<Option name="properties" type="Map">\s*</Option>',
                     '<Option name="properties"/>', cleaned)
    return qml[:start] + cleaned + qml[end:], True


def apply(qml):
    """Returns (qml, 'applied'|'already')."""
    qml, stripped = strip_text_style_color(qml)
    if stripped:
        print("removed the inactive Color property from the text-style block")
    start, end, block = settings_dd(qml)
    want = expression()
    if 'name="Color"' in block:
        found = re.search(r'<Option name="Color" type="Map">.*?'
                          r'name="expression" type="QString" value="([^"]*)"',
                          block, re.S)
        if found and found.group(1) == xml_attr(want):
            return qml, ("applied" if stripped else "already")
        bail("the labeling already carries a Color property with a "
             "different expression - refusing to overwrite: %s"
             % (found.group(1) if found else "<no expression>"))

    empty = re.search(r'<Option name="properties"\s*/>', block)
    if empty:
        new_block = (block[:empty.start()]
                     + '<Option name="properties" type="Map">'
                     + property_xml() + '</Option>'
                     + block[empty.end():])
    else:
        m = re.search(r'<Option name="properties" type="Map">', block)
        if not m:
            bail("settings dd_properties has no properties Option")
        new_block = (block[:m.end()] + property_xml() + block[m.end():])
    return qml[:start] + new_block + qml[end:], "applied"


def main():
    default = os.path.join(REPO, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)

    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    row = cur.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    if not row or not row[0]:
        bail("styleQML missing for %r" % LAYER)
    qml = row[0]

    before_textcolor = re.search(r'<text-style[^>]*\btextColor="([^"]*)"',
                                 qml).group(1)

    qml, state = apply(qml)
    print("label token %s: %s"
          % (cover_palette.rgb_hex(cover_palette.LABEL_TOKEN), state))

    if state == "applied":
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail("edited style no longer parses, not writing: %s" % exc)
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("styleQML updated")

    # ---------------- round-trip validation ---------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    final = cur.execute(
        "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()[0]
    ET.fromstring(final)

    _s, _e, block = settings_dd(final)
    assert 'name="Color"' in block, "Color property did not survive"
    assert xml_attr(expression()) in block
    # ... and nowhere else: a text-style copy would be inert and confusing.
    _ts_s, _ts_e, style_block = _text_style_span(final)
    assert 'name="Color"' not in style_block, (
        "an inactive Color property is still sitting in the text-style")
    # inject_label_cartography.py owns this attribute; it must be untouched.
    after = re.search(r'<text-style[^>]*\btextColor="([^"]*)"',
                      final).group(1)
    assert after == before_textcolor, (before_textcolor, after)
    # And the label expression itself is nobody's business here.
    assert final.count("<text-style") == 1

    print("round-trip ok: cover labels %s, bedrock labels %s, static "
          "textColor untouched"
          % (cover_palette.rgb_hex(cover_palette.LABEL_TOKEN),
             cover_palette.rgb_hex(cover_palette.LABEL_BEDROCK)))
    con.close()


if __name__ == "__main__":
    main()
