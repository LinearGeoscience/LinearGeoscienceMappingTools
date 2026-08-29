"""Paint cover round 4: cream fills, the bright Ora Banda amber.

Round 3 went whisper + gold, but on the map the tans read salmon and the
gold read brown (see cover_palette.py's docstring for the full story).
Round 4 moves every cover fill to true cream / near-paper and both gold
carriers to the bright amber off the reference map. The numbers live in
scripts/cover_palette.py; this script only writes them into the template.

Same moves as round 3, new values:
  SimpleFill  color        -> the code's cream fill
  SimpleLine  line_color   -> GOLD_CONTACT (amber)
  SimpleLine  outlineColor -> amber, inside the untouched ContactType CASE
  SLD         fill/stroke  -> the same two colours
  labeling    dd Color     -> LABEL_TOKEN swapped in the settings-level
                              expression ('#835f11' -> the amber)

Idempotent: every code must be fully on its round-3 colours or fully on
its round-4 ones, QML and SLD alike; the label expression must be exactly
round 3's or round 4's. Anything in between aborts without writing.

Run on a round-3 template (the label-declutter merge carries one); run
inject_basemap_lith_patterns.py after to re-bake - that run also applies
the new COVER_INK_TARGET softening to the cover textures.

Usage:  python scripts/inject_cover_gold_round4.py [path\\to\\gpkg]
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
import inject_cover_mechanism as r2
import inject_cover_gold_round3 as r3
import inject_cover_label_token as tok

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYER = r2.LAYER
TABLE = r2.TABLE
KEEP = r2.KEEP

BACKUP_NAME = "LGS_MappingTemplate_pre-cover-round4_2026-08-29.gpkg"

bail = r2.bail


def round3_expression():
    """Round 3's label-colour expression, rebuilt verbatim."""
    return ("CASE WHEN \"%s\" = '%s' THEN '%s' ELSE '%s' END"
            % (tok.FIELD, tok.COVER_TYPE,
               cover_palette.rgb_hex(cover_palette.ROUND3_LABEL_TOKEN),
               cover_palette.rgb_hex(cover_palette.LABEL_BEDROCK)))


def swap_label_token(qml):
    """Round 3's token -> round 4's, in the settings-level dd Color.
    Returns (qml, 'applied'|'already')."""
    start, _end, block = tok.settings_dd(qml)
    found = re.search(r'<Option name="Color" type="Map">.*?'
                      r'name="expression" type="QString" value="([^"]*)"',
                      block, re.S)
    if not found:
        bail("the settings dd_properties has no Color property - run "
             "inject_cover_label_token.py first")
    want = tok.xml_attr(tok.expression())
    old = tok.xml_attr(round3_expression())
    if found.group(1) == want:
        return qml, "already"
    if found.group(1) != old:
        bail("the labeling Color expression is neither round 3's nor round "
             "4's - refusing to overwrite: %s" % found.group(1))
    abs_s = start + found.start(1)
    abs_e = start + found.end(1)
    return qml[:abs_s] + want + qml[abs_e:], "applied"


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
        bail("codes not in %s: %s" % (TABLE, missing))
    not_cover = sorted(c for c, t in rows.items()
                       if t != "Transported Cover")
    if not_cover:
        bail("codes not typed 'Transported Cover': %s" % not_cover)
    if sorted(cover_palette.ROUND3_FILLS) != sorted(cover_palette.COVER):
        bail("ROUND3_FILLS does not cover the palette 1:1")

    row = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    if not row or not row[0] or not row[1]:
        bail("styleQML/styleSLD missing for %r" % LAYER)
    qml, sld = row
    keep_before = {c: r2.code_colours(qml, c) for c in KEEP}
    before_textcolor = re.search(r'<text-style[^>]*\btextColor="([^"]*)"',
                                 qml).group(1)

    # ---------------- edit --------------------------------------------
    gold = cover_palette.GOLD_CONTACT
    old_gold = cover_palette.ROUND3_CONTACT
    states = {}
    for code in sorted(cover_palette.COVER):
        fill = cover_palette.fill_of(code)
        old_fill = cover_palette.ROUND3_FILLS[code]
        qml, q_state = r3.paint_symbol(qml, code, old_fill, old_gold,
                                       fill, gold)
        sld, s_state = r3.paint_sld(sld, code, old_fill, old_gold,
                                    fill, gold)
        if q_state != s_state:
            bail("%s: QML says %r but SLD says %r - templates half-applied"
                 % (code, q_state, s_state))
        states[code] = q_state
        print("  %-6s %-8s %s -> %s   %s"
              % (code, cover_palette.family_of(code),
                 cover_palette.rgb_hex(old_fill),
                 cover_palette.rgb_hex(fill), q_state))

    qml, l_state = swap_label_token(qml)
    print("label token %s -> %s: %s"
          % (cover_palette.rgb_hex(cover_palette.ROUND3_LABEL_TOKEN),
             cover_palette.rgb_hex(cover_palette.LABEL_TOKEN), l_state))
    states["<label>"] = l_state

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
        print("styleQML + styleSLD updated (%d cover codes + label token)"
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
        _s, _e, block = r2.block_of(final_qml, code)
        assert r2.triple_of(
            r2._colour_option(block, "color").group(1)) == fill, code
        assert r2.triple_of(
            r2._colour_option(block, "line_color").group(1)) == gold, code
        expr = r2._outline_expr(block).group(1)
        assert {(int(r), int(g), int(b))
                for r, g, b, _a in r2.RGBA_RE.findall(expr)} == {gold}, code
        alphas = [a for _r, _g, _b, a in r2.RGBA_RE.findall(expr)]
        assert alphas == ["0", "255"], (code, alphas)
        assert '"ContactType"' in expr.replace("&quot;", '"'), code
        rule = r2.sld_rule_span(final_sld, code).group(0)
        assert re.findall(r'name="fill">(#[0-9a-fA-F]{6})', rule) == \
            [cover_palette.rgb_hex(fill)], code
        assert re.findall(r'name="stroke">(#[0-9a-fA-F]{6})', rule) == \
            [cover_palette.rgb_hex(gold)], code

    for code, was in keep_before.items():
        assert r2.code_colours(final_qml, code) == was, (
            code, "colour moved but this script must not touch it")

    for code in ("SST", "RCC", "SSL"):
        _s, _e, block = r2.block_of(final_qml, code)
        expr = r2._outline_expr(block)
        assert expr and {(int(r), int(g), int(b)) for r, g, b, _a
                         in r2.RGBA_RE.findall(expr.group(1))} == \
            {cover_palette.CONTACT_BEDROCK}, code

    _s, _e, dd_block = tok.settings_dd(final_qml)
    assert tok.xml_attr(tok.expression()) in dd_block, "label token missing"
    _ts_s, _ts_e, style_block = tok._text_style_span(final_qml)
    assert 'name="Color"' not in style_block
    after = re.search(r'<text-style[^>]*\btextColor="([^"]*)"',
                      final_qml).group(1)
    assert after == before_textcolor, (before_textcolor, after)

    anchors = {}
    for code, rgb in r2.all_anchors(final_qml).items():
        anchors.setdefault(rgb, []).append(code)
    shared = {cover_palette.rgb_hex(cover_palette.fill_of(c)):
              anchors[cover_palette.fill_of(c)]
              for c in cover_palette.COVER
              if len(anchors.get(cover_palette.fill_of(c), [c])) > 1}
    assert not shared, "cover anchors shared with other codes: %s" % shared

    # ---------------- dE audit ----------------------------------------
    tex = lith_palette.read_texture_map()
    bedrock_fills = {c: rgb for c, rgb in r2.all_anchors(final_qml).items()
                     if c not in cover_palette.COVER}
    bedrock_tiles = {c: tex[c][0] for c in bedrock_fills if c in tex}
    problems = cover_palette.audit(bedrock_fills, bedrock_tiles)
    if problems:
        for p in problems:
            print("   AUDIT " + p)
        bail("%d palette rules broken against the live template" % len(problems))
    print("audit: clean (hard same-tile dE >= %.0f, cream floor %.1f, pair "
          "floor %.1f, unique anchors, contact legibility %.2f)"
          % (cover_palette.MIN_FILL_DE, cover_palette.CREAM_DE,
             cover_palette.COVER_PAIR_DE, cover_palette.MIN_CONTACT_RATIO))

    print("\nround-trip ok: %d cover codes on the amber register (contact "
          "%s, label %s). Re-run inject_basemap_lith_patterns.py to bake "
          "the patterns template with the softened cover ink."
          % (len(cover_palette.COVER), cover_palette.rgb_hex(gold),
             cover_palette.rgb_hex(cover_palette.LABEL_TOKEN)))
    con.close()


if __name__ == "__main__":
    main()
