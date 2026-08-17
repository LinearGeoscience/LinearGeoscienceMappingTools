"""Give the stranded H* metamorphic codes real colours in the live template.

THE PROBLEM
-----------
28 `H*` codes shared ONE placeholder fill, `#cf5870` - which is also the fill
of the NULL / all-other-values category. So in the shipped template most
metamorphics and "uncoded" drew identically, and `#cf5870` sits on the same
hue as the granitoid pink `#feafc2` (just darker), so metamorphics read as
granitoids.

`lith_palette.PROTOLITH` masks part of this in the patterns template by
re-basing 16 of the 28 onto their protolith's colour. But five of those were
re-based onto family F's MODAL colour, and F's modal is the intrusive pink
(it wins 17-13 over the extrusive yellow) - so felsic gneiss, felsic
granulite and charnockite came out pink anyway, and the terracotta the user
had deliberately set on HGG / HGGA was thrown away with them.

WHAT THIS DOES
--------------
Recolours 13 codes in `4 - Basemap`, by sub-family, so the H family reads as
metamorphic rather than as pink:

  * felsic gneiss / granulite / charnockite -> the user's own HGG / HGGA
    terracotta, so the whole high-grade felsic gneiss group is one family and
    cannot be confused with a granitoid.
  * the six fault rocks -> neutral warm greys, which is the convention for
    them and separates them from every composition-coloured family.
  * marble / calc-silicate / skarn / hornfels -> pale sea-green, pale olive,
    olive-brown and warm brown.

Deliberately NOT touched:
  * `HMI` migmatite and `HGT` garnetite keep their pinks - migmatite is
    granitic melt and garnet is red, so pink IS the signal there (user's call).
  * `HGG` / `HGGA` already carry the terracotta this script aims the others at.
  * The 14 protolith-based H codes (HAMP, HBL, HEC, HGI, HGM, HGU, HIG, HMG,
    HPA, HPC, HPH, HPK, HPMA, HSL) still hold the placeholder HERE. The
    patterns template re-bases them to their protolith (mafic teal,
    sedimentary blue, ultramafic purple), so they render correctly there; in
    this template they remain pink. That divergence is pre-existing, not
    introduced here - see the note at the end of the run output.
  * The NULL / all-other-values category keeps `#cf5870`. After this change it
    is the only thing left on that colour, which makes "uncoded" distinctive
    instead of ambiguous.

The 19 granitoid codes are not touched either - the fix is to move the
metamorphics, not the granite convention.

Colour lives in the live template because `lith_palette.read_code_anchors()`
reads it from here: change it here, re-run `inject_basemap_lith_patterns.py`,
and both templates agree. Editing the patterns copy directly is wiped on the
next injector run.

Idempotent: each code must be either fully on the placeholder or fully on its
new colour, in the QML and the SLD alike. Anything else aborts without
writing.

Usage:  python scripts/inject_basemap_h_recolour.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "4 - Basemap"
TABLE = "BasemapCodes"

# The shared placeholder every target currently carries.
PLACEHOLDER = (207, 88, 112)          # #cf5870

# code -> new fill. Grouped by how the rock is read on a map, not by letter.
RECOLOUR = {
    # High-grade felsic gneiss family, aimed at the user's own HGG #d96a4e /
    # HGGA #e3876f terracotta so the group holds together and reads clearly
    # apart from granitoid pink.
    "HFG":  (0xe0, 0x9a, 0x72),       # Felsic Gneiss
    "HGF":  (0xd4, 0x79, 0x4f),       # Felsic Granulite
    "HCK":  (0xc8, 0x6a, 0x44),       # Charnockite granite

    # Fault rocks -> neutral warm greys, graded by intensity of deformation
    # (gouge palest, pseudotachylite darkest). Grey is the convention and it
    # keeps them out of every composition-coloured family.
    "HGOU": (0xa7, 0x9d, 0x92),       # Fault Gouge
    "HCAT": (0x9a, 0x90, 0x86),       # Cataclasite
    "HFBX": (0x8e, 0x85, 0x7b),       # Fault Breccia
    "HMY":  (0x82, 0x78, 0x6f),       # Mylonite
    "HUMY": (0x6f, 0x67, 0x5e),       # Ultramylonite
    # #6b6259 not #5d564f: lith_palette.L_MIN = 0.34 would clamp the darker
    # value, so the patterns template would silently disagree with this one.
    "HPST": (0x6b, 0x62, 0x59),       # Pseudotachylite

    # Contact and carbonate metamorphics.
    "HMB":  (0xc3, 0xdd, 0xd2),       # Marble - pale sea-green
    "HCS":  (0xc8, 0xcf, 0x9e),       # Calc-Silicate Rock - pale olive
    "HSK":  (0xa8, 0xa0, 0x5c),       # Skarn - olive-brown
    "HHF":  (0xb0, 0x89, 0x68),       # Hornfels - warm brown
}

# Codes that must still be on the placeholder afterwards, as a guard that
# this script has not reached further than intended.
KEEP_PLACEHOLDER = [
    "HAMP", "HBL", "HEC", "HGI", "HGM", "HGU", "HIG", "HMG",
    "HPA", "HPC", "HPH", "HPK", "HPMA", "HSL", "HMI", "NULL",
]

BACKUP_NAME = "LGS_MappingTemplate_pre-h-recolour_2026-08-17.gpkg"


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def rgb_hex(rgb):
    return "#%02x%02x%02x" % rgb


def qml_colour(rgb):
    """QGIS's own serialisation: 'r,g,b,a,rgb:R,G,B,A' with float channels."""
    r, g, b = rgb
    return "%d,%d,%d,255,rgb:%s,%s,%s,1" % (
        r, g, b, repr(r / 255.0), repr(g / 255.0), repr(b / 255.0))


def triple_of(value):
    m = re.match(r'\s*(\d+),(\d+),(\d+)', value)
    return tuple(int(x) for x in m.groups()) if m else None


def symbol_block(qml, name):
    """(start, end) of <symbol name="..."> ... </symbol>, nesting-aware."""
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), qml)
    if not m:
        bail("symbol %r not found" % name)
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', qml[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail("unbalanced symbol %r" % name)


def symbol_for_value(qml, value):
    cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(value), qml)
    if not cm:
        bail("category %r not found in %s" % (value, LAYER))
    return re.search(r'symbol="(\d+)"', cm.group(0)).group(1)


def block_colours(block):
    """Every colour Option value in a symbol block, as (match, triple)."""
    out = []
    for m in re.finditer(r'<Option name="(?:color|line_color)" '
                         r'type="QString" value="([^"]*)"', block):
        t = triple_of(m.group(1))
        if t:
            out.append((m, t))
    return out


def recolour_symbol(qml, code, rgb):
    """Repaint one category's symbol. Returns (qml, state) where state is
    'applied', 'already' or aborts."""
    s, e = symbol_block(qml, symbol_for_value(qml, code))
    block = qml[s:e]
    cols = block_colours(block)
    if not cols:
        bail("%s: symbol carries no colour options" % code)
    triples = {t for _m, t in cols}
    if triples == {rgb}:
        return qml, "already"
    if triples != {PLACEHOLDER}:
        bail("%s: symbol colours are %s, expected all %s (placeholder) or "
             "all %s (target) - refusing to guess"
             % (code, sorted(triples), PLACEHOLDER, rgb))
    new = qml_colour(rgb)
    out, last = [], 0
    for m, _t in cols:
        out.append(block[last:m.start(1)])
        out.append(new)
        last = m.end(1)
    out.append(block[last:])
    return qml[:s] + "".join(out) + qml[e:], "applied"


def sld_rule_span(sld, code):
    needle = "<ogc:Literal>%s</ogc:Literal>" % code
    for m in re.finditer(r'<se:Rule>.*?</se:Rule>', sld, re.S):
        if needle in m.group(0):
            return m
    return None


def recolour_sld(sld, code, rgb):
    m = sld_rule_span(sld, code)
    if m is None:
        bail("SLD rule for %r not found" % code)
    rule = m.group(0)
    found = set(re.findall(r'<se:SvgParameter name="(?:fill|stroke)">'
                           r'(#[0-9a-fA-F]{6})</se:SvgParameter>', rule))
    want, old = rgb_hex(rgb), rgb_hex(PLACEHOLDER)
    if found == {want}:
        return sld, "already"
    if found != {old}:
        bail("%s: SLD colours are %s, expected all %s or all %s"
             % (code, sorted(found), old, want))
    new_rule = re.sub(r'(<se:SvgParameter name="(?:fill|stroke)">)'
                      r'#[0-9a-fA-F]{6}(</se:SvgParameter>)',
                      r'\g<1>%s\g<2>' % want, rule)
    return sld[:m.start()] + new_rule + sld[m.end():], "applied"


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - colour belongs in the "
             "live template; run inject_basemap_lith_patterns.py afterwards")

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # ---------------- guards ------------------------------------------
    have = {c for (c,) in cur.execute(
        "SELECT Code FROM %s WHERE Code IN (%s)"
        % (TABLE, ",".join("?" * len(RECOLOUR))), sorted(RECOLOUR))}
    missing = sorted(set(RECOLOUR) - have)
    if missing:
        bail("codes not in %s: %s" % (TABLE, missing))

    row = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    if not row or not row[0] or not row[1]:
        bail("styleQML/styleSLD missing for %r" % LAYER)
    qml, sld = row
    before_placeholders = len(re.findall(
        r'value="%d,%d,%d,' % PLACEHOLDER, qml))

    # ---------------- edit --------------------------------------------
    states = {}
    for code in sorted(RECOLOUR):
        rgb = RECOLOUR[code]
        qml, q_state = recolour_symbol(qml, code, rgb)
        sld, s_state = recolour_sld(sld, code, rgb)
        if q_state != s_state:
            bail("%s: QML says %r but SLD says %r - templates half-applied"
                 % (code, q_state, s_state))
        states[code] = q_state
        print("  %-6s %s -> %s   %s"
              % (code, rgb_hex(PLACEHOLDER), rgb_hex(rgb), q_state))

    if set(states.values()) == {"already"}:
        print("already applied (no change)")
    elif "already" in set(states.values()):
        bail("partially applied: %s"
             % sorted(c for c, s in states.items() if s == "already"))
    else:
        # Never persist a style that no longer parses.
        try:
            ET.fromstring(qml)
            ET.fromstring(sld)
        except ET.ParseError as exc:
            bail("edited style no longer parses, not writing: %s" % exc)
        if not os.path.exists(os.path.join(repo, "Template", "Backup",
                                           BACKUP_NAME)):
            shutil.copy2(gpkg, os.path.join(repo, "Template", "Backup",
                                            BACKUP_NAME))
            print("backup -> Template/Backup/%s" % BACKUP_NAME)
        cur.execute("UPDATE layer_styles SET styleQML=?, styleSLD=? "
                    "WHERE f_table_name=?", (qml, sld, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("styleQML + styleSLD updated (%d codes)" % len(RECOLOUR))

    # ---------------- round-trip validation ---------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    final_qml, final_sld = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    root = ET.fromstring(final_qml)
    ET.fromstring(final_sld)

    rend = re.search(r'<renderer-v2\b[^>]*>', final_qml).group(0)
    assert 'type="categorizedSymbol"' in rend and 'attr="Lithology1"' in rend
    assert 'referencescale="5000"' in rend
    cats = root.find(".//renderer-v2/categories").findall("category")
    assert len(cats) == 284, len(cats)

    for code, rgb in sorted(RECOLOUR.items()):
        s, e = symbol_block(final_qml, symbol_for_value(final_qml, code))
        got = {t for _m, t in block_colours(final_qml[s:e])}
        assert got == {rgb}, (code, got)
        rule = sld_rule_span(final_sld, code).group(0)
        assert set(re.findall(r'<se:SvgParameter name="(?:fill|stroke)">'
                              r'(#[0-9a-fA-F]{6})</se:SvgParameter>',
                              rule)) == {rgb_hex(rgb)}, code
    for code in KEEP_PLACEHOLDER:
        s, e = symbol_block(final_qml, symbol_for_value(final_qml, code))
        got = {t for _m, t in block_colours(final_qml[s:e])}
        assert got == {PLACEHOLDER}, (code, "should still be placeholder", got)

    after = len(re.findall(r'value="%d,%d,%d,' % PLACEHOLDER, final_qml))
    print("placeholder colour occurrences: %d -> %d (%d codes moved x2 "
          "options each)" % (before_placeholders, after, len(RECOLOUR)))
    assert len(re.findall(r'<se:Rule>', final_sld)) == 285

    print("round-trip ok: %d codes recoloured in QML and SLD, %d codes and "
          "NULL still on the placeholder" % (len(RECOLOUR),
                                             len(KEEP_PLACEHOLDER) - 1))
    print("\nNOTE: the 14 protolith-based H codes (%s) still hold %s in THIS "
          "template. They render correctly in the patterns template because "
          "lith_palette re-bases them onto their protolith. Fixing them here "
          "too is a separate decision - ask before doing it."
          % (", ".join(KEEP_PLACEHOLDER[:5]) + ", ...", rgb_hex(PLACEHOLDER)))
    con.close()


if __name__ == "__main__":
    main()
