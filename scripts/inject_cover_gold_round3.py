"""Paint cover round 3: whisper fills, one gold contact, gold label token.

Round 2 (inject_cover_mechanism.py) gave every cover family a hue and a
tinted contact. On the map it was too loud - the colluvial green competed
with the lithology - so round 3 turns the register down to the Ora Banda
look: fills compressed into a near-paper whisper band (colluvium now
buff-tan, not green), and ONE antique gold for every cover contact and
every cover label. The numbers and the reasoning live in
scripts/cover_palette.py; this script only writes them into the template.

WHAT MOVES, PER COVER CATEGORY
------------------------------
  SimpleFill  color        -> the code's whisper fill
  SimpleLine  line_color   -> GOLD_CONTACT
  SimpleLine  outlineColor -> GOLD_CONTACT, inside the ContactType CASE
  SLD         fill/stroke  -> the same two colours
  labeling    dd Color     -> LABEL_TOKEN swapped into the settings-level
                              expression (the c354ba7 lesson: the
                              text-style copy is inert; only the block
                              after </text-style> is read by the renderer)

WHAT DOES NOT MOVE
------------------
The ContactType mechanism (Solid/Dashed/None keep their dash, width and
alpha - only the RGB moves), the static textColor, the label expression,
everything outside Transported Cover. Bedrock keeps #2a2a2a contacts and
black labels; the KEEP list is snapshotted before and compared after.

Idempotent: every code must be fully on its round-2 colours or fully on
its round-3 ones, QML and SLD alike, and the label expression must be
exactly round 2's or exactly round 3's. Anything in between aborts
without writing.

Run AFTER inject_cover_mechanism.py's state exists (i.e. on a round-2
template); run inject_basemap_lith_patterns.py after to re-bake the
patterns template.

Round 3 gave cover a size step as well as this colour - 6.5 pt against the
lithology 5.5 - so it read as its own identity twice over. That half was
dropped on 30 Aug 2026 and cover now letters at the lithology size; the gold
below is the whole identity. inject_label_size_scaling.py owns the Size
property and no longer branches on cover at all.

Usage:  python scripts/inject_cover_gold_round3.py [path\\to\\gpkg]
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
import inject_cover_label_token as tok

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYER = r2.LAYER
TABLE = r2.TABLE
KEEP = r2.KEEP

BACKUP_NAME = "LGS_MappingTemplate_pre-cover-round3_2026-08-29.gpkg"

bail = r2.bail


def old_expression():
    """Round 2's label-colour expression, rebuilt verbatim."""
    return ("CASE WHEN \"%s\" = '%s' THEN '%s' ELSE '%s' END"
            % (tok.FIELD, tok.COVER_TYPE,
               cover_palette.rgb_hex(cover_palette.ROUND2_LABEL_TOKEN),
               cover_palette.rgb_hex(cover_palette.LABEL_BEDROCK)))


def paint_symbol(qml, code, old_fill, old_contact, fill, contact):
    """Repaint one category. Returns (qml, state): 'applied' or 'already'."""
    s, e, block = r2.block_of(qml, code)

    fill_m = r2._colour_option(block, "color")
    line_m = r2._colour_option(block, "line_color")
    expr_m = r2._outline_expr(block)
    if not (fill_m and line_m and expr_m):
        bail("%s: symbol is missing a colour option (fill=%s line=%s expr=%s)"
             % (code, bool(fill_m), bool(line_m), bool(expr_m)))

    have_fill = r2.triple_of(fill_m.group(1))
    have_line = r2.triple_of(line_m.group(1))
    have_expr = {(int(r), int(g), int(b))
                 for r, g, b, _a in r2.RGBA_RE.findall(expr_m.group(1))}
    if not have_expr:
        bail("%s: outlineColor expression carries no color_rgba()" % code)

    done = (have_fill == fill and have_line == contact
            and have_expr == {contact})
    todo = (have_fill == old_fill and have_line == old_contact
            and have_expr == {old_contact})
    if done:
        return qml, "already"
    if not todo:
        bail("%s: unexpected colours (fill %s, line %s, contact %s) - "
             "expected all-round-2 (%s / %s) or all-round-3 (%s / %s); "
             "refusing to guess"
             % (code, have_fill, have_line, sorted(have_expr), old_fill,
                old_contact, fill, contact))

    new_expr = r2.RGBA_RE.sub(
        lambda m: "color_rgba(%d, %d, %d, %s)"
                  % (contact[0], contact[1], contact[2], m.group(4)),
        expr_m.group(1))
    # Rebuild back-to-front so the earlier spans stay valid.
    out = block
    for m, value in sorted(((fill_m, r2.qml_colour(fill)),
                            (line_m, r2.qml_colour(contact)),
                            (expr_m, new_expr)),
                           key=lambda p: p[0].start(1), reverse=True):
        out = out[:m.start(1)] + value + out[m.end(1):]
    return qml[:s] + out + qml[e:], "applied"


def paint_sld(sld, code, old_fill, old_contact, fill, contact):
    m = r2.sld_rule_span(sld, code)
    if m is None:
        bail("SLD rule for %r not found" % code)
    rule = m.group(0)
    fills = re.findall(r'<se:SvgParameter name="fill">(#[0-9a-fA-F]{6})'
                       r'</se:SvgParameter>', rule)
    strokes = re.findall(r'<se:SvgParameter name="stroke">(#[0-9a-fA-F]{6})'
                         r'</se:SvgParameter>', rule)
    want_f = cover_palette.rgb_hex(fill)
    want_s = cover_palette.rgb_hex(contact)
    was_f = cover_palette.rgb_hex(old_fill)
    was_s = cover_palette.rgb_hex(old_contact)
    if set(fills) == {want_f} and set(strokes) == {want_s}:
        return sld, "already"
    if set(fills) != {was_f} or set(strokes) != {was_s}:
        bail("%s: SLD colours are fill %s / stroke %s, expected the round-2 "
             "pair %s / %s or the round-3 pair %s / %s"
             % (code, sorted(set(fills)), sorted(set(strokes)), was_f, was_s,
                want_f, want_s))
    rule = re.sub(r'(<se:SvgParameter name="fill">)#[0-9a-fA-F]{6}'
                  r'(</se:SvgParameter>)', r'\g<1>%s\g<2>' % want_f, rule)
    rule = re.sub(r'(<se:SvgParameter name="stroke">)#[0-9a-fA-F]{6}'
                  r'(</se:SvgParameter>)', r'\g<1>%s\g<2>' % want_s, rule)
    return sld[:m.start()] + rule + sld[m.end():], "applied"


def swap_label_token(qml):
    """Move the settings-level dd Color expression from round 2's token to
    round 3's. Returns (qml, 'applied'|'already')."""
    start, end, block = tok.settings_dd(qml)
    found = re.search(r'<Option name="Color" type="Map">.*?'
                      r'name="expression" type="QString" value="([^"]*)"',
                      block, re.S)
    if not found:
        bail("the settings dd_properties has no Color property - run "
             "inject_cover_label_token.py first")
    want = tok.xml_attr(tok.expression())
    old = tok.xml_attr(old_expression())
    if found.group(1) == want:
        return qml, "already"
    if found.group(1) != old:
        bail("the labeling Color expression is neither round 2's nor round "
             "3's - refusing to overwrite: %s" % found.group(1))
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
        bail("codes not in %s: %s - run the round-2 injectors first"
             % (TABLE, missing))
    not_cover = sorted(c for c, t in rows.items()
                       if t != "Transported Cover")
    if not_cover:
        bail("codes not typed 'Transported Cover': %s" % not_cover)
    if sorted(cover_palette.ROUND2_FILLS) != sorted(cover_palette.COVER):
        bail("ROUND2_FILLS does not cover the palette 1:1")

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
    states = {}
    for code in sorted(cover_palette.COVER):
        fill = cover_palette.fill_of(code)
        old_fill = cover_palette.ROUND2_FILLS[code]
        old_contact = cover_palette.ROUND2_CONTACT[
            cover_palette.family_of(code)]
        qml, q_state = paint_symbol(qml, code, old_fill, old_contact,
                                    fill, gold)
        sld, s_state = paint_sld(sld, code, old_fill, old_contact,
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
          % (cover_palette.rgb_hex(cover_palette.ROUND2_LABEL_TOKEN),
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
        # The ContactType mechanism must be intact: two branches, and the
        # alpha still 0 for 'None' and 255 otherwise.
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

    # Bedrock keeps the near-black contact: spot-check the guards that have
    # one (NULL's catch-all symbol included).
    for code in ("SST", "RCC", "SSL"):
        _s, _e, block = r2.block_of(final_qml, code)
        expr = r2._outline_expr(block)
        assert expr and {(int(r), int(g), int(b)) for r, g, b, _a
                         in r2.RGBA_RE.findall(expr.group(1))} == \
            {cover_palette.CONTACT_BEDROCK}, code

    # The gold label token lives in the settings dd block, nowhere else,
    # and the statics it must not touch are untouched.
    _s, _e, dd_block = tok.settings_dd(final_qml)
    assert tok.xml_attr(tok.expression()) in dd_block, "label token missing"
    _ts_s, _ts_e, style_block = tok._text_style_span(final_qml)
    assert 'name="Color"' not in style_block
    after = re.search(r'<text-style[^>]*\btextColor="([^"]*)"',
                      final_qml).group(1)
    assert after == before_textcolor, (before_textcolor, after)

    # Anchor uniqueness: build() only passes a colour through untouched when
    # no other code shares the anchor.
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
    print("audit: clean (same-tile dE >= %.0f, cream audit, unique anchors, "
          "contact legibility)" % cover_palette.MIN_FILL_DE)

    for s_code in cover_palette.SANDSTONE_CREAMS:
        s_fill = bedrock_fills[s_code]
        near = min((cover_palette.delta_e(cover_palette.fill_of(c), s_fill), c)
                   for c in cover_palette.COVER)
        print("  vs %-5s %s: nearest cover %s at dE %.1f"
              % (s_code, cover_palette.rgb_hex(s_fill), near[1], near[0]))

    print("\nround-trip ok: %d cover codes on the gold register (contact %s, "
          "label %s). Re-run inject_basemap_lith_patterns.py to bake the "
          "patterns template, and inject_label_size_scaling.py for the "
          "cover label size."
          % (len(cover_palette.COVER),
             cover_palette.rgb_hex(gold),
             cover_palette.rgb_hex(cover_palette.LABEL_TOKEN)))
    con.close()


if __name__ == "__main__":
    main()
