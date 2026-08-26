"""Add ZBXS Silica Breccia + SSTS/SSLS transitional sed liths (Aug 2026).

User request, 27 Aug 2026: three new BasemapCodes, applied to the lookup
table AND the '4 - Basemap' renderer QML AND the SLD, in lockstep (audit
precedent - every category has a matching se:Rule):

    - ZBXS Silica Breccia: separable from ZBXSI Silica Flood Breccia.
      Code chosen to sit beside its sibling in every dropdown. Cloned
      from ZBXSI (253,184,100) in a paler, greyer tone. In the PATTERNS
      template it joins ZBXSI in lith_palette's sheared/S-protolith set,
      with a LIGHTNESS_NUDGE keeping the pair separable there too.
    - SSTS Silty Sandstone: clone of SST, fill interpolated SST -> SSL
      but nearer SST. Declares tsv variety `sandstone` (like SSTF/SSTL),
      so it joins that bucket without shifting anyone's slot offsets.
    - SSLS Sandy Siltstone: clone of SSL, fill interpolated SSL -> SST
      but nearer SSL, warmed enough to clear MIN_FILL_DE against SSL's
      resolved grey in the patterns build.

Fids append 284-286 (current max 283); symbols allocate names 293-295
(max in use 292). Table UUIDs, category uuids and symbol layer ids are
deterministic uuid5 (same namespaces as inject_basemap_new_lith_codes)
so re-runs are stable. '4 - Basemap' has 0 features - nothing migrates.

Idempotent and re-runnable: each edit group (3 rows, 3 categories +
symbols, 3 SLD rules) must be exactly 0 or its full count, anything else
aborts without writing.

After this, add the three lith_textures.tsv rows and re-run
inject_basemap_lith_patterns.py to re-bake the patterns template.

Usage:  python scripts/inject_lith_codes_2026_08.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

LAYER = "4 - Basemap"
TABLE = "BasemapCodes"

FIRST_FID = 284     # current max(fid) = 283
FIRST_SYMBOL = 293  # current max renderer symbol name = 292

# code, Type, description (stored/labelled as "CODE - desc"), clone source
# code, fill RGB. Order fixes fid and symbol allocation - do not reorder.
NEW_CODES = [
    ("ZBXS", "Lithology", "Silica Breccia", "ZBXSI", (241, 205, 150)),
    ("SSTS", "Lithology", "Silty Sandstone", "SST", (228, 219, 192)),
    ("SSLS", "Lithology", "Sandy Siltstone", "SSL", (219, 215, 196)),
]
EXPECT_ROWS_AFTER = 286
EXPECT_CATS_AFTER = 287   # 286 codes + NULL catch-all
EXPECT_RULES_AFTER = 288


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def label_for(code, desc):
    return f"{code} - {desc}"


def table_uuid(code):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "lgs-lith-row:" + code))


def category_uuid(code):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL, "lgs-lith-cat:" + code)


def layer_id(code, index):
    return "{%s}" % uuid.uuid5(uuid.NAMESPACE_URL,
                               f"lgs-lith-code:{code}:{index}")


def rgb_qml(rgb):
    return "%d,%d,%d,255" % rgb


def rgb_hex(rgb):
    return "#%02x%02x%02x" % rgb


def symbol_block(q, name):
    m = re.search(r'<symbol\b[^>]*\bname="%s"[^>]*>' % re.escape(name), q)
    if not m:
        bail(f"symbol {name!r} not found")
    depth = 0
    for t in re.finditer(r'<symbol\b|</symbol>', q[m.start():]):
        depth += 1 if t.group(0) == '<symbol' else -1
        if depth == 0:
            return m.start(), m.start() + t.end()
    bail(f"unbalanced symbol {name!r}")


def symbol_for_value(qml, value):
    cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(value), qml)
    if not cm:
        bail(f"Basemap category {value!r} not found")
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
        bail(f"{source_code!r}: unexpected layer stack "
             f"{[l.get('class') for l in layers]}")
    for i, lyr in enumerate(layers):
        lyr.set("id", layer_id(code, i))
        opts = direct_opts(lyr)
        key = "color" if lyr.get("class") == "SimpleFill" else "line_color"
        if key not in opts:
            bail(f"{source_code!r}: {lyr.get('class')} has no {key}")
        # line_color matches the fill by convention (render-time it is
        # overridden by the ContactType outlineColor expression anyway).
        opts[key].set("value", rgb_qml(rgb))
    return ET.tostring(sym_el, encoding="unicode")


def sld_rule_for(sld, code):
    needle = f"<ogc:Literal>{code}</ogc:Literal>"
    for m in re.finditer(r'<se:Rule>.*?</se:Rule>', sld, re.S):
        if needle in m.group(0):
            return m
    return None


def clone_sld_rule(sld, source_code, code, label, rgb):
    m = sld_rule_for(sld, source_code)
    if m is None:
        bail(f"SLD rule for {source_code!r} not found")
    rule = m.group(0)
    xml_label = escape(label)
    rule = re.sub(r'<se:Name>.*?</se:Name>',
                  f'<se:Name>{xml_label}</se:Name>', rule, count=1, flags=re.S)
    rule = re.sub(r'<se:Title>.*?</se:Title>',
                  f'<se:Title>{xml_label}</se:Title>', rule, count=1, flags=re.S)
    rule = rule.replace(f"<ogc:Literal>{source_code}</ogc:Literal>",
                        f"<ogc:Literal>{code}</ogc:Literal>")
    rule, n = re.subn(r'(<se:SvgParameter name="fill">)#[0-9a-fA-F]{6}'
                      r'(</se:SvgParameter>)',
                      r'\g<1>%s\g<2>' % rgb_hex(rgb), rule, count=1)
    if n != 1:
        bail(f"SLD rule for {source_code!r}: fill parameter not found")
    return rule


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # ---------------- table state + guards ---------------------------
    for source in ("ZBXSI", "SST", "SSL"):
        if not cur.execute(f"SELECT 1 FROM {TABLE} WHERE Code=?",
                           (source,)).fetchone():
            bail(f"clone source {source!r} missing from {TABLE}")

    existing = {c for (c,) in cur.execute(
        f"SELECT Code FROM {TABLE} WHERE Code IN (%s)"
        % ",".join("?" * len(NEW_CODES)), [c[0] for c in NEW_CODES])}
    if existing and len(existing) != len(NEW_CODES):
        bail(f"partial code state: {sorted(existing)} already present")
    inserts_needed = not existing
    if inserts_needed:
        max_fid = cur.execute(f"SELECT MAX(fid) FROM {TABLE}").fetchone()[0]
        if max_fid != FIRST_FID - 1:
            bail(f"max(fid) is {max_fid}, expected {FIRST_FID - 1} - "
                 "re-check FIRST_FID")

    # ---------------- styles ------------------------------------------
    row = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    if not row or not row[0] or not row[1]:
        bail(f"styleQML/styleSLD missing for {LAYER!r}")
    qml, sld = row

    rm = re.search(r'<renderer-v2\b.*?</renderer-v2>', qml, re.S)
    if not rm:
        bail("renderer-v2 block not found")
    renderer = rm.group(0)

    # -- QML categories + symbols (0 or 3) --
    present = [c for c, *_ in NEW_CODES if f'value="{c}"' in renderer]
    if present and len(present) != len(NEW_CODES):
        bail(f"partial category state: {present}")
    cats_needed = not present
    if cats_needed:
        for i in range(len(NEW_CODES)):
            if re.search(r'<symbol\b[^>]*\bname="%d"' % (FIRST_SYMBOL + i),
                         renderer):
                bail(f"symbol name {FIRST_SYMBOL + i} already in use - "
                     "re-check FIRST_SYMBOL")
        cat_lines = []
        sym_blocks = []
        for i, (code, _type, desc, source, rgb) in enumerate(NEW_CODES):
            name = str(FIRST_SYMBOL + i)
            cat_lines.append(
                '<category render="true" type="string" label="%s" '
                'value="%s" uuid="%s" symbol="%s"/>'
                % (escape(label_for(code, desc), {'"': "&quot;"}),
                   code, category_uuid(code), name))
            sym_blocks.append(clone_symbol(renderer, source, name, code, rgb))
            print(f"{code}: category + symbol {name} (clone of {source}, "
                  f"{rgb_hex(rgb)})")
        close_cats = renderer.index("</categories>")
        renderer = (renderer[:close_cats] + "".join(cat_lines)
                    + renderer[close_cats:])
        close_syms = renderer.index("</symbols>")
        renderer = (renderer[:close_syms] + "".join(sym_blocks)
                    + renderer[close_syms:])

    new_qml = qml[:rm.start()] + renderer + qml[rm.end():]

    # -- SLD new rules (0 or 3) --
    sld_present = [c for c, *_ in NEW_CODES if sld_rule_for(sld, c)]
    if sld_present and len(sld_present) != len(NEW_CODES):
        bail(f"partial SLD state: {sld_present}")
    sld_needed = not sld_present
    if sld_needed:
        rules = [clone_sld_rule(sld, source, code, label_for(code, desc), rgb)
                 for code, _type, desc, source, rgb in NEW_CODES]
        close_fts = sld.index("</se:FeatureTypeStyle>")
        sld = sld[:close_fts] + "".join(rules) + sld[close_fts:]
        print(f"SLD: {len(rules)} rules appended")

    if not any([inserts_needed, cats_needed, sld_needed]):
        print("already applied (no change)")
    else:
        if len({inserts_needed, cats_needed, sld_needed}) != 1:
            bail("insert state differs between table/QML/SLD")
        # Validate BEFORE writing: never persist styles that no longer parse.
        try:
            ET.fromstring(new_qml)
            ET.fromstring(sld)
        except ET.ParseError as exc:
            bail(f"edited style no longer parses, aborting without write: {exc}")

        for i, (code, type_, desc, _source, _rgb) in enumerate(NEW_CODES):
            cur.execute(
                f"INSERT INTO {TABLE} (fid, Type, Code, Description, UUID)"
                " VALUES (?,?,?,?,?)",
                (FIRST_FID + i, type_, code, label_for(code, desc),
                 table_uuid(code)))
        cur.execute(
            "UPDATE layer_styles SET styleQML=?, styleSLD=? WHERE f_table_name=?",
            (new_qml, sld, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("BasemapCodes + styleQML + styleSLD updated")

    # ---------------- validation --------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    n = cur.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    assert n == EXPECT_ROWS_AFTER, n
    uuids = [r[0] for r in cur.execute(f"SELECT UUID FROM {TABLE}")]
    assert len(set(uuids)) == n and all(len(x) == 36 for x in uuids)
    for code, type_, desc, _s, _rgb in NEW_CODES:
        got = cur.execute(
            f"SELECT Type, Description FROM {TABLE} WHERE Code=?",
            (code,)).fetchone()
        assert got == (type_, label_for(code, desc)), (code, got)

    final_qml, final_sld = cur.execute(
        "SELECT styleQML, styleSLD FROM layer_styles WHERE f_table_name=?",
        (LAYER,)).fetchone()
    root = ET.fromstring(final_qml)
    ET.fromstring(final_sld)
    print(f"QML+SLD parse: {LAYER}")

    rend = re.search(r'<renderer-v2\b[^>]*>', final_qml).group(0)
    assert 'type="categorizedSymbol"' in rend and 'attr="Lithology1"' in rend
    assert 'referencescale="5000"' in rend
    renderer_el = root.find(".//renderer-v2")
    cats = renderer_el.find("categories").findall("category")
    assert len(cats) == EXPECT_CATS_AFTER, len(cats)
    values = [c.get("value") for c in cats]
    for code, *_ in NEW_CODES:
        assert values.count(code) == 1, code
    assert "NULL" in values
    sym_names = {s.get("name") for s in renderer_el.find("symbols")}
    for i in range(len(NEW_CODES)):
        assert str(FIRST_SYMBOL + i) in sym_names, FIRST_SYMBOL + i
    assert "FilterExpression" in final_qml  # ValueRelation config survives
    rules = re.findall(r'<se:Rule>', final_sld)
    assert len(rules) == EXPECT_RULES_AFTER, len(rules)
    for code, *_ in NEW_CODES:
        assert final_sld.count(f"<ogc:Literal>{code}</ogc:Literal>") == 1, code
    print(f"round-trip ok: {EXPECT_ROWS_AFTER} codes, {EXPECT_CATS_AFTER} "
          f"categories, {EXPECT_RULES_AFTER} SLD rules")
    con.close()


if __name__ == "__main__":
    main()
