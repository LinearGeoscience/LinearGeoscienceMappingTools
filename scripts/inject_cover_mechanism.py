"""Paint the Transported Cover register: mechanism-tinted fills + contacts.

Round 1 (inject_basemap_cover_recolour.py) moved cover off the sandstone
cream onto one grey ladder so it stopped reading as bedrock. This is round
2: the ladder keeps its lightness rungs but takes a family HUE that says how
the material got where it is - blue for water-lain, olive for hillslope,
pink for wind, icy cyan for ice, teal for coast, and so on - and the cover
CONTACT stops being bedrock's #2a2a2a and takes a mid-tone of its family.

The numbers, the families and the reasoning all live in
scripts/cover_palette.py; this script only writes them into the template.

WHAT MOVES, PER CATEGORY
------------------------
  SimpleFill  color        -> the code's family fill
  SimpleLine  line_color   -> the family contact tint
  SimpleLine  outlineColor -> same tint, inside the ContactType CASE
  SLD         fill/stroke  -> the same two colours

WHAT DOES NOT MOVE
------------------
The ContactType mechanism itself. Solid/Dashed/None still choose the dash
pattern (customDash), the width (outlineWidth) and the transparency - the
alpha argument of each color_rgba() is left exactly as found, so a 'None'
contact stays invisible and a 'Solid' one stays solid. Only the RGB moves.
That was the user's explicit call: tinted cover contacts, same mechanism.

Nor does anything outside Transported Cover: bedrock keeps #2a2a2a
contacts, and the KEEP list is snapshotted before and compared after.

Idempotent: every code must be fully on its old colours or fully on its new
ones, in the QML and the SLD alike. Anything in between aborts without
writing. Run inject_cover_codes_round2.py FIRST - this script requires all
34 cover codes to exist.

Usage:  python scripts/inject_cover_mechanism.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import shutil
import sqlite3
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cover_palette
import lith_palette

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYER = "4 - Basemap"
TABLE = "BasemapCodes"

# Codes whose colour must be untouched afterwards, as a guard that this
# script has not reached further than intended.
KEEP = ["SST", "SSTM", "SSTS", "SSLS", "SSL", "SEV", "RSLS", "RARZ", "RCC",
        "RDLP", "NULL"]

BACKUP_NAME = "LGS_MappingTemplate_pre-cover-round2_2026-08-28.gpkg"


def bail(msg):
    raise SystemExit("ABORT: " + msg)


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


def block_of(qml, code):
    s, e = symbol_block(qml, symbol_for_value(qml, code))
    return s, e, qml[s:e]


def _colour_option(block, name):
    """The (start, end) of one colour Option's value attribute."""
    m = re.search(r'<Option name="%s" type="QString" value="([^"]*)"' % name,
                  block)
    return m


RGBA_RE = re.compile(r'color_rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,'
                     r'\s*(\d+)\s*\)')


def _outline_expr(block):
    """(start, end) of the SimpleLine outlineColor expression's value."""
    key = block.find('<Option name="outlineColor" type="Map">')
    if key < 0:
        return None
    m = re.compile(r'<Option name="expression" type="QString" '
                   r'value="([^"]*)"').search(block, key)
    return m


def paint_symbol(qml, code, old_fill, fill, contact):
    """Repaint one category. Returns (qml, state): 'applied' or 'already'."""
    s, e, block = block_of(qml, code)

    fill_m = _colour_option(block, "color")
    line_m = _colour_option(block, "line_color")
    expr_m = _outline_expr(block)
    if not (fill_m and line_m and expr_m):
        bail("%s: symbol is missing a colour option (fill=%s line=%s expr=%s)"
             % (code, bool(fill_m), bool(line_m), bool(expr_m)))

    have_fill = triple_of(fill_m.group(1))
    have_line = triple_of(line_m.group(1))
    have_expr = {(int(r), int(g), int(b))
                 for r, g, b, _a in RGBA_RE.findall(expr_m.group(1))}
    if not have_expr:
        bail("%s: outlineColor expression carries no color_rgba()" % code)

    done = (have_fill == fill and have_line == contact
            and have_expr == {contact})
    todo = (have_fill == old_fill and have_line == old_fill
            and have_expr == {cover_palette.CONTACT_BEDROCK})
    if done:
        return qml, "already"
    if not todo:
        bail("%s: unexpected colours (fill %s, line %s, contact %s) - "
             "expected all-old (%s / %s) or all-new (%s / %s); refusing to "
             "guess"
             % (code, have_fill, have_line, sorted(have_expr), old_fill,
                cover_palette.CONTACT_BEDROCK, fill, contact))

    new_expr = RGBA_RE.sub(
        lambda m: "color_rgba(%d, %d, %d, %s)"
                  % (contact[0], contact[1], contact[2], m.group(4)),
        expr_m.group(1))
    # Rebuild back-to-front so the earlier spans stay valid.
    out = block
    for m, value in sorted(((fill_m, qml_colour(fill)),
                            (line_m, qml_colour(contact)),
                            (expr_m, new_expr)),
                           key=lambda p: p[0].start(1), reverse=True):
        out = out[:m.start(1)] + value + out[m.end(1):]
    return qml[:s] + out + qml[e:], "applied"


def sld_rule_span(sld, code):
    needle = "<ogc:Literal>%s</ogc:Literal>" % code
    for m in re.finditer(r'<se:Rule>.*?</se:Rule>', sld, re.S):
        if needle in m.group(0):
            return m
    return None


def paint_sld(sld, code, old_fill, fill, contact):
    m = sld_rule_span(sld, code)
    if m is None:
        bail("SLD rule for %r not found" % code)
    rule = m.group(0)
    fills = re.findall(r'<se:SvgParameter name="fill">(#[0-9a-fA-F]{6})'
                       r'</se:SvgParameter>', rule)
    strokes = re.findall(r'<se:SvgParameter name="stroke">(#[0-9a-fA-F]{6})'
                         r'</se:SvgParameter>', rule)
    want_f, want_s = cover_palette.rgb_hex(fill), cover_palette.rgb_hex(contact)
    was = cover_palette.rgb_hex(old_fill)
    if set(fills) == {want_f} and set(strokes) == {want_s}:
        return sld, "already"
    if set(fills) != {was} or set(strokes) != {was}:
        bail("%s: SLD colours are fill %s / stroke %s, expected all %s "
             "or the new pair %s / %s"
             % (code, sorted(set(fills)), sorted(set(strokes)), was,
                want_f, want_s))
    rule = re.sub(r'(<se:SvgParameter name="fill">)#[0-9a-fA-F]{6}'
                  r'(</se:SvgParameter>)', r'\g<1>%s\g<2>' % want_f, rule)
    rule = re.sub(r'(<se:SvgParameter name="stroke">)#[0-9a-fA-F]{6}'
                  r'(</se:SvgParameter>)', r'\g<1>%s\g<2>' % want_s, rule)
    return sld[:m.start()] + rule + sld[m.end():], "applied"


def code_colours(qml, code):
    """Every colour option in a category's symbol, for the KEEP snapshot."""
    _s, _e, block = block_of(qml, code)
    out = {t for t in (triple_of(m.group(1)) for m in re.finditer(
        r'<Option name="(?:color|line_color|outline_color)" '
        r'type="QString" value="([^"]*)"', block)) if t}
    expr = _outline_expr(block)
    if expr:
        out |= {(int(r), int(g), int(b))
                for r, g, b, _a in RGBA_RE.findall(expr.group(1))}
    return sorted(out)


def all_anchors(qml):
    """{code: SimpleFill rgb} for every category - the same scrape (and the
    same ANCHOR_OVERRIDE) as lith_palette.read_code_anchors()."""
    sym = {}
    for m in re.finditer(r'<symbol[^>]*name="(\d+)"', qml):
        seg = qml[m.start():m.start() + 2500]
        c = re.search(r'class="SimpleFill".*?<Option name="color" '
                      r'type="QString" value="(\d+),(\d+),(\d+)', seg, re.S)
        if c:
            sym[m.group(1)] = tuple(int(x) for x in c.groups())
    out = {}
    for m in re.finditer(r'<category([^>]*)\>', qml):
        a = m.group(1)
        v = re.search(r'value="([^"]*)"', a)
        s = re.search(r'symbol="(\d+)"', a)
        if not (v and s) or s.group(1) not in sym:
            continue
        code = v.group(1)
        if not code or code == "NULL":
            continue
        out[code] = sym[s.group(1)]
    out.update(lith_palette.ANCHOR_OVERRIDE)
    return out


def main():
    default = os.path.join(REPO, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - colour belongs in "
             "the live template; run inject_basemap_lith_patterns.py after")

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # ---------------- guards ------------------------------------------
    rows = dict(cur.execute(
        "SELECT Code, Type FROM %s WHERE Code IN (%s)"
        % (TABLE, ",".join("?" * len(cover_palette.COVER))),
        sorted(cover_palette.COVER)))
    missing = sorted(set(cover_palette.COVER) - set(rows))
    if missing:
        bail("codes not in %s: %s - run inject_cover_codes_round2.py first"
             % (TABLE, missing))
    not_cover = sorted(c for c, t in rows.items()
                       if t != "Transported Cover")
    if not_cover:
        bail("codes not typed 'Transported Cover': %s" % not_cover)
    n_cover = cur.execute(
        "SELECT COUNT(*) FROM %s WHERE Type='Transported Cover'"
        % TABLE).fetchone()[0]
    if n_cover != len(cover_palette.COVER):
        bail("%s holds %d cover codes but the palette lists %d"
             % (TABLE, n_cover, len(cover_palette.COVER)))

    row = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    if not row or not row[0] or not row[1]:
        bail("styleQML/styleSLD missing for %r" % LAYER)
    qml, sld = row
    keep_before = {c: code_colours(qml, c) for c in KEEP}

    # ---------------- edit --------------------------------------------
    states = {}
    for code in sorted(cover_palette.COVER):
        fill = cover_palette.fill_of(code)
        contact = cover_palette.contact_of(code)
        # Round 1's codes arrive on their grey; round 2's own arrive already
        # on their family fill (inject_cover_codes_round2.py paints them),
        # so for those the fill is a no-op and only the contact moves.
        old_fill = cover_palette.ROUND1_GREY.get(code, fill)
        qml, q_state = paint_symbol(qml, code, old_fill, fill, contact)
        sld, s_state = paint_sld(sld, code, old_fill, fill, contact)
        if q_state != s_state:
            bail("%s: QML says %r but SLD says %r - templates half-applied"
                 % (code, q_state, s_state))
        states[code] = q_state
        print("  %-6s %-8s %s -> %s   contact %s   %s"
              % (code, cover_palette.family_of(code),
                 cover_palette.rgb_hex(old_fill), cover_palette.rgb_hex(fill),
                 cover_palette.rgb_hex(contact), q_state))

    if set(states.values()) == {"already"}:
        print("already applied (no change)")
    elif len(set(states.values())) > 1:
        bail("partially applied: %s"
             % sorted(c for c, s in states.items() if s == "already"))
    else:
        try:
            ET.fromstring(qml)
            ET.fromstring(sld)
        except ET.ParseError as exc:
            bail("edited style no longer parses, not writing: %s" % exc)
        backup = os.path.join(REPO, "Template", "Backup", BACKUP_NAME)
        if not os.path.exists(backup):
            shutil.copy2(gpkg, backup)
            print("backup -> Template/Backup/%s" % BACKUP_NAME)
        cur.execute("UPDATE layer_styles SET styleQML=?, styleSLD=? "
                    "WHERE f_table_name=?", (qml, sld, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("styleQML + styleSLD updated (%d cover codes)"
              % len(cover_palette.COVER))

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
    assert len(cats) == 300, len(cats)          # 299 codes + NULL catch-all
    assert len(re.findall(r'<se:Rule>', final_sld)) == 301

    for code in sorted(cover_palette.COVER):
        fill = cover_palette.fill_of(code)
        contact = cover_palette.contact_of(code)
        _s, _e, block = block_of(final_qml, code)
        assert triple_of(_colour_option(block, "color").group(1)) == fill, code
        assert triple_of(
            _colour_option(block, "line_color").group(1)) == contact, code
        expr = _outline_expr(block).group(1)
        assert {(int(r), int(g), int(b))
                for r, g, b, _a in RGBA_RE.findall(expr)} == {contact}, code
        # The ContactType mechanism must be intact: two branches, and the
        # alpha still 0 for 'None' and 255 otherwise.
        alphas = [a for _r, _g, _b, a in RGBA_RE.findall(expr)]
        assert alphas == ["0", "255"], (code, alphas)
        assert '"ContactType"' in expr.replace("&quot;", '"'), code
        rule = sld_rule_span(final_sld, code).group(0)
        assert re.findall(r'name="fill">(#[0-9a-fA-F]{6})', rule) == \
            [cover_palette.rgb_hex(fill)], code
        assert re.findall(r'name="stroke">(#[0-9a-fA-F]{6})', rule) == \
            [cover_palette.rgb_hex(contact)], code

    for code, was in keep_before.items():
        assert code_colours(final_qml, code) == was, (
            code, "colour moved but this script must not touch it")

    # Bedrock keeps the near-black contact: spot-check the guards that have
    # one (NULL's catch-all symbol included).
    for code in ("SST", "RCC", "SSL"):
        _s, _e, block = block_of(final_qml, code)
        expr = _outline_expr(block)
        assert expr and {(int(r), int(g), int(b)) for r, g, b, _a
                         in RGBA_RE.findall(expr.group(1))} == \
            {cover_palette.CONTACT_BEDROCK}, code

    # Anchor uniqueness: build() only passes a colour through untouched when
    # no other code shares the anchor.
    anchors = {}
    for code, rgb in all_anchors(final_qml).items():
        anchors.setdefault(rgb, []).append(code)
    shared = {cover_palette.rgb_hex(cover_palette.fill_of(c)):
              anchors[cover_palette.fill_of(c)]
              for c in cover_palette.COVER
              if len(anchors.get(cover_palette.fill_of(c), [c])) > 1}
    assert not shared, "cover anchors shared with other codes: %s" % shared

    # ---------------- dE audit ----------------------------------------
    tex = lith_palette.read_texture_map()
    bedrock_fills = {c: rgb for c, rgb in all_anchors(final_qml).items()
                     if c not in cover_palette.COVER}
    bedrock_tiles = {c: tex[c][0] for c in bedrock_fills if c in tex}
    problems = cover_palette.audit(bedrock_fills, bedrock_tiles)
    if problems:
        for p in problems:
            print("   AUDIT " + p)
        bail("%d palette rules broken against the live template" % len(problems))
    print("audit: clean (same-tile dE >= %.0f, cream audit, unique anchors, "
          "contact legibility)" % cover_palette.MIN_FILL_DE)

    for s_code in cover_palette.SANDSTONE_CREAMS:
        s_fill = bedrock_fills[s_code]
        near = min((cover_palette.delta_e(cover_palette.fill_of(c), s_fill), c)
                   for c in cover_palette.COVER)
        print("  vs %-5s %s: nearest cover %s at dE %.1f"
              % (s_code, cover_palette.rgb_hex(s_fill), near[1], near[0]))

    print("\nround-trip ok: %d cover codes on %d mechanism families, "
          "contacts tinted, ContactType mechanism intact. Re-run "
          "inject_basemap_lith_patterns.py to bake the patterns template."
          % (len(cover_palette.COVER), len(cover_palette.FAMILY_CONTACT)))
    con.close()


if __name__ == "__main__":
    main()
