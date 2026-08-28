"""Add the 13 Transported Cover codes round 2 needs, for global mapping.

WHY THESE THIRTEEN
------------------
The shipped 21 were built for one Australian regolith setting: alluvium,
colluvium, lag, duricrust, salt pan. Read against the old Ora Banda project
(whose most-used cover code by far was a compound "lag on colluvium", and
which needed a sheetwash code the list has never had) and against how the
list travels - Canada, Iceland, Indonesia have no code to pick at all - the
gaps are mechanical: nothing for ice, nothing for a coast, nothing for
airfall, nothing organic, nothing anthropogenic.

    TSW   Sheetwash                  unchannelled sheet flow
    TLGC  Lag on Colluvium           the old project's workhorse compound
    TAES  Aeolian Sand               dunes/sand sheet, distinct from TSA
    TLAC  Lacustrine Clay            playa and lake bed, distinct from TCY
    TLOE  Loess                      aeolian silt
    TTIL  Glacial Till               unsorted, matrix-supported
    TGFO  Glaciofluvial Outwash      meltwater sand and gravel
    TBCH  Beach & Coastal Sand
    TMUD  Tidal & Estuarine Mud
    TASH  Volcanic Ash               airfall tephra
    TFIL  Anthropogenic Fill         dumps, tailings, road fill
    TLSD  Landslide & Debris Flow    mass movement
    TPEA  Peat & Organic Soil        bog and swamp, a heavy bedrock mask

Each is a MATERIAL, like every code already in the list. Landform codes
(alluvial fan, terrace) were considered and left out: they are TALL by
material and would introduce a second, crossing axis.

WHAT THIS DOES
--------------
Adds each code to BasemapCodes, to the '4 - Basemap' renderer (category +
cloned symbol) and to the SLD (cloned rule), in lockstep - the audit
precedent is that every category has a matching se:Rule - and appends the
matching row to Template/patterns/lith_textures.tsv, which the patterns
injector refuses to run unless it is exactly 1:1 with BasemapCodes.

Colour comes from scripts/cover_palette.py, so a code is born on the same
fill inject_cover_mechanism.py would give it; that injector then paints the
contacts (and moves the 21 older codes onto their family hues).

Fids append 287-299 and symbols 296-308. UUIDs, category uuids and symbol
layer ids are deterministic uuid5, so re-runs are stable. '4 - Basemap'
holds no features, so nothing migrates.

Idempotent: each edit group (13 rows, 13 categories, 13 symbols, 13 SLD
rules, 13 texture rows) must be exactly 0 or 13, anything else aborts
without writing.

Usage:  python scripts/inject_cover_codes_round2.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cover_palette

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXTURE_MAP = os.path.join(REPO, "Template", "patterns", "lith_textures.tsv")

LAYER = "4 - Basemap"
TABLE = "BasemapCodes"
TYPE = "Transported Cover"

FIRST_FID = 287     # current max(fid) = 286
FIRST_SYMBOL = 296  # current max renderer symbol name = 295

NEW_CODES = cover_palette.NEW_CODES          # [(code, clone source), ...]

EXPECT_ROWS_AFTER = 299
EXPECT_CATS_AFTER = 300   # 299 codes + NULL catch-all
EXPECT_RULES_AFTER = 301  # the SLD carries one rule beyond the categories


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def label_for(code):
    return "%s - %s" % (code, cover_palette.description_of(code))


def table_uuid(code):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "lgs-lith-row:" + code))


def category_uuid(code):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-lith-cat:" + code)


def layer_id(code, index):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL,
                               "lgs-lith-code:%s:%d" % (code, index))


def rgb_qml(rgb):
    return "%d,%d,%d,255" % tuple(rgb)


def symbol_block(q, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail("symbol %r not found" % name)
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail("unbalanced symbol %r" % name)


def symbol_for_value(qml, value):
    cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(value), qml)
    if not cm:
        bail("Basemap category %r not found" % value)
    return re.search(r'symbol="(\d+)"', cm.group(0)).group(1)


def direct_opts(layer_el):
    cont = layer_el.find("Option")
    if cont is None:
        return {}
    return {o.get("name"): o for o in cont.findall("Option")}


def clone_symbol(renderer, source_code, new_name, code, rgb):
    """Clone source_code's symbol block: new name, fresh layer ids, colour."""
    s, e = symbol_block(renderer, symbol_for_value(renderer, source_code))
    sym_el = ET.fromstring(renderer[s:e])
    sym_el.set("name", new_name)
    layers = sym_el.findall("layer")
    if [l.get("class") for l in layers] != ["SimpleFill", "SimpleLine"]:
        bail("%r: unexpected layer stack %s"
             % (source_code, [l.get("class") for l in layers]))
    for i, lyr in enumerate(layers):
        lyr.set("id", layer_id(code, i))
        opts = direct_opts(lyr)
        key = "color" if lyr.get("class") == "SimpleFill" else "line_color"
        if key not in opts:
            bail("%r: %s has no %s" % (source_code, lyr.get("class"), key))
        # line_color matches the fill on arrival; inject_cover_mechanism.py
        # moves it (and the ContactType outlineColor expression it is
        # overridden by) onto the family contact tint.
        opts[key].set("value", rgb_qml(rgb))
    return ET.tostring(sym_el, encoding="unicode")


def sld_rule_for(sld, code):
    needle = "<ogc:Literal>%s</ogc:Literal>" % code
    for m in re.finditer(r'<se:Rule>.*?</se:Rule>', sld, re.S):
        if needle in m.group(0):
            return m
    return None


def clone_sld_rule(sld, source_code, code, label, rgb):
    m = sld_rule_for(sld, source_code)
    if m is None:
        bail("SLD rule for %r not found" % source_code)
    rule = m.group(0)
    xml_label = escape(label)
    rule = re.sub(r'<se:Name>.*?</se:Name>',
                  '<se:Name>%s</se:Name>' % xml_label, rule, count=1,
                  flags=re.S)
    rule = re.sub(r'<se:Title>.*?</se:Title>',
                  '<se:Title>%s</se:Title>' % xml_label, rule, count=1,
                  flags=re.S)
    rule = rule.replace("<ogc:Literal>%s</ogc:Literal>" % source_code,
                        "<ogc:Literal>%s</ogc:Literal>" % code)
    # Fill AND stroke: every cover rule in the shipped SLD carries the same
    # colour in both, and inject_cover_mechanism.py checks for exactly that
    # before it moves the stroke onto the family contact tint. Painting the
    # fill alone would leave the clone source's colour on the stroke.
    rule, n = re.subn(r'(<se:SvgParameter name="(?:fill|stroke)">)'
                      r'#[0-9a-fA-F]{6}(</se:SvgParameter>)',
                      r'\g<1>%s\g<2>' % cover_palette.rgb_hex(rgb), rule)
    if n != 2:
        bail("SLD rule for %r: expected one fill and one stroke parameter, "
             "painted %d" % (source_code, n))
    return rule


def texture_rows():
    """The lith_textures.tsv lines for the new codes, in file order."""
    return {code: "%s\t%s\t%s\t%s\t%s\tauto\t-"
                  % (code, cover_palette.tile_of(code), TYPE,
                     cover_palette.description_of(code),
                     cover_palette.note_of(code))
            for code, _src in NEW_CODES}


def update_texture_map():
    """Insert the new codes into lith_textures.tsv. Returns True if written.

    The file is grouped by Type - Lithology, then Regolith, then Transported
    Cover - and code-sorted WITHIN each group. Only the cover block is
    rebuilt, so the diff is thirteen inserted lines and nothing else moves.
    """
    with open(TEXTURE_MAP, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    have = {l.split("\t")[0] for l in lines
            if l.strip() and not l.startswith("#")}
    wanted = texture_rows()
    present = sorted(c for c in wanted if c in have)
    if present and len(present) != len(wanted):
        bail("partial texture-map state: %s already present" % present)
    if present:
        return False

    cover_at = [i for i, l in enumerate(lines)
                if l.strip() and not l.startswith("#")
                and l.split("\t")[2:3] == [TYPE]]
    if not cover_at:
        bail("no %r rows in the texture map to insert beside" % TYPE)
    if cover_at != list(range(cover_at[0], cover_at[-1] + 1)):
        bail("the %r rows are not contiguous - refusing to re-sort the file"
             % TYPE)
    block = sorted(lines[cover_at[0]:cover_at[-1] + 1] + list(wanted.values()),
                   key=lambda l: l.split("\t")[0])
    out = lines[:cover_at[0]] + block + lines[cover_at[-1] + 1:]
    with open(TEXTURE_MAP, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out))
    print("lith_textures.tsv: %d rows inserted" % len(wanted))
    return True


def main():
    default = os.path.join(REPO, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    if "_Patterns" in os.path.basename(gpkg):
        bail("that is the generated patterns template - codes belong in the "
             "live template; run inject_basemap_lith_patterns.py afterwards")

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # ---------------- table state + guards ---------------------------
    for _code, source in NEW_CODES:
        row = cur.execute("SELECT Type FROM %s WHERE Code=?" % TABLE,
                          (source,)).fetchone()
        if not row:
            bail("clone source %r missing from %s" % (source, TABLE))
        if row[0] != TYPE:
            bail("clone source %r is typed %r, not %r"
                 % (source, row[0], TYPE))

    codes = [c for c, _s in NEW_CODES]
    existing = {c for (c,) in cur.execute(
        "SELECT Code FROM %s WHERE Code IN (%s)"
        % (TABLE, ",".join("?" * len(codes))), codes)}
    if existing and len(existing) != len(codes):
        bail("partial code state: %s already present" % sorted(existing))
    inserts_needed = not existing
    if inserts_needed:
        max_fid = cur.execute("SELECT MAX(fid) FROM %s" % TABLE).fetchone()[0]
        if max_fid != FIRST_FID - 1:
            bail("max(fid) is %s, expected %d - re-check FIRST_FID"
                 % (max_fid, FIRST_FID - 1))

    # ---------------- styles ------------------------------------------
    row = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    if not row or not row[0] or not row[1]:
        bail("styleQML/styleSLD missing for %r" % LAYER)
    qml, sld = row

    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("renderer-v2 block not found")
    renderer = rm.group(0)

    present = [c for c in codes if 'value="%s"' % c in renderer]
    if present and len(present) != len(codes):
        bail("partial category state: %s" % present)
    cats_needed = not present
    if cats_needed:
        for i in range(len(NEW_CODES)):
            if re.search(r'<symbol\b[^>]*\bname="%d"' % (FIRST_SYMBOL + i),
                         renderer):
                bail("symbol name %d already in use - re-check FIRST_SYMBOL"
                     % (FIRST_SYMBOL + i))
        cat_lines, sym_blocks = [], []
        for i, (code, source) in enumerate(NEW_CODES):
            name = str(FIRST_SYMBOL + i)
            rgb = cover_palette.fill_of(code)
            cat_lines.append(
                '<category render="true" type="string" label="%s" '
                'value="%s" uuid="%s" symbol="%s"/>'
                % (escape(label_for(code), {'"': "&quot;"}), code,
                   category_uuid(code), name))
            sym_blocks.append(clone_symbol(renderer, source, name, code, rgb))
            print("%-5s category + symbol %s (clone of %s, %s)"
                  % (code, name, source, cover_palette.rgb_hex(rgb)))
        close_cats = renderer.index("</categories>")
        renderer = (renderer[:close_cats] + "".join(cat_lines)
                    + renderer[close_cats:])
        close_syms = renderer.index("</symbols>")
        renderer = (renderer[:close_syms] + "".join(sym_blocks)
                    + renderer[close_syms:])

    new_qml = qml[:rm.start()] + renderer + qml[rm.end():]

    sld_present = [c for c in codes if sld_rule_for(sld, c)]
    if sld_present and len(sld_present) != len(codes):
        bail("partial SLD state: %s" % sld_present)
    sld_needed = not sld_present
    if sld_needed:
        rules = [clone_sld_rule(sld, source, code, label_for(code),
                                cover_palette.fill_of(code))
                 for code, source in NEW_CODES]
        close_fts = sld.index("</se:FeatureTypeStyle>")
        sld = sld[:close_fts] + "".join(rules) + sld[close_fts:]
        print("SLD: %d rules appended" % len(rules))

    if not any([inserts_needed, cats_needed, sld_needed]):
        print("already applied (no change)")
    else:
        if len({inserts_needed, cats_needed, sld_needed}) != 1:
            bail("insert state differs between table/QML/SLD")
        try:
            ET.fromstring(new_qml)
            ET.fromstring(sld)
        except ET.ParseError as exc:
            bail("edited style no longer parses, not writing: %s" % exc)

        for i, (code, _source) in enumerate(NEW_CODES):
            cur.execute(
                "INSERT INTO %s (fid, Type, Code, Description, UUID)"
                " VALUES (?,?,?,?,?)" % TABLE,
                (FIRST_FID + i, TYPE, code, label_for(code),
                 table_uuid(code)))
        cur.execute("UPDATE layer_styles SET styleQML=?, styleSLD=? "
                    "WHERE f_table_name=?", (new_qml, sld, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("BasemapCodes + styleQML + styleSLD updated")

    update_texture_map()

    # ---------------- validation --------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    n = cur.execute("SELECT COUNT(*) FROM %s" % TABLE).fetchone()[0]
    assert n == EXPECT_ROWS_AFTER, n
    n_cover = cur.execute("SELECT COUNT(*) FROM %s WHERE Type=?" % TABLE,
                          (TYPE,)).fetchone()[0]
    assert n_cover == len(cover_palette.COVER), n_cover
    uuids = [r[0] for r in cur.execute("SELECT UUID FROM %s" % TABLE)]
    assert len(set(uuids)) == n and all(len(x) == 36 for x in uuids)
    for code, _source in NEW_CODES:
        got = cur.execute(
            "SELECT Type, Description FROM %s WHERE Code=?" % TABLE,
            (code,)).fetchone()
        assert got == (TYPE, label_for(code)), (code, got)

    final_qml, final_sld = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    root = ET.fromstring(final_qml)
    ET.fromstring(final_sld)

    rend = re.search(r'<renderer-v2\b[^>]*>', final_qml).group(0)
    assert 'type="categorizedSymbol"' in rend and 'attr="Lithology1"' in rend
    assert 'referencescale="5000"' in rend
    renderer_el = root.find(".//renderer-v2")
    cats = renderer_el.find("categories").findall("category")
    assert len(cats) == EXPECT_CATS_AFTER, len(cats)
    values = [c.get("value") for c in cats]
    for code, _source in NEW_CODES:
        assert values.count(code) == 1, code
    assert "NULL" in values
    sym_names = {s.get("name") for s in renderer_el.find("symbols")}
    for i in range(len(NEW_CODES)):
        assert str(FIRST_SYMBOL + i) in sym_names, FIRST_SYMBOL + i
    assert "FilterExpression" in final_qml   # ValueRelation config survives
    rules = re.findall(r'<se:Rule>', final_sld)
    assert len(rules) == EXPECT_RULES_AFTER, len(rules)
    for code, _source in NEW_CODES:
        assert final_sld.count("<ogc:Literal>%s</ogc:Literal>" % code) == 1

    # The patterns injector refuses to run unless the texture map is exactly
    # 1:1 with BasemapCodes; prove that here rather than there.
    with open(TEXTURE_MAP, encoding="utf-8") as fh:
        mapped = {l.split("\t")[0] for l in fh
                  if l.strip() and not l.startswith("#")
                  and not l.startswith("code\t")}
    table_codes = {c for (c,) in cur.execute("SELECT Code FROM %s" % TABLE)}
    assert mapped == table_codes, (
        "texture map and %s disagree: %s"
        % (TABLE, sorted(mapped ^ table_codes)))

    print("round-trip ok: %d codes (%d cover), %d categories, %d SLD rules, "
          "texture map 1:1"
          % (EXPECT_ROWS_AFTER, n_cover, EXPECT_CATS_AFTER,
             EXPECT_RULES_AFTER))
    con.close()


if __name__ == "__main__":
    main()
