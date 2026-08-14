"""Add the Aug 2026 lithology codes; rename HSPG -> HPPG.

User-supplied spreadsheet (emailed): 11 new BasemapCodes + one rename,
applied to the lookup table AND the '4 - Basemap' renderer QML AND the
SLD, in lockstep (audit precedent - every category has a matching
se:Rule):

    - HSPG -> HPPG (fid 71, "Semi-Pelitic Gneiss"): code made consistent
      with SPP - Semipelite (psammopelite), and kills the HPSG/HSPG
      near-anagram. NOTE the spreadsheet said "fid 213" - that is its own
      row number; gpkg fid 213 is ZI - Intermediate Schist and is
      guarded untouched here. The rename target was confirmed by UUID
      (68955728-...). Symbol 215 is kept - rename only.
    - TDLP Duricrust of Transported Pisoliths (Transported Cover; the
      cover-visibility toggle picks it up automatically - it filters on
      TypeLith1, never on code lists) - RDLP duricrust colour per user.
    - FPGS Felsic Pegmatite Spodumene-bearing; HGT Garnetite; HGG/HGGA
      Granite (Augen) Gneiss; HMID/HMIM/HMIT/HMIN/HMIS/HMIP migmatite
      suite. Symbols are cloned from nearest siblings with a graded
      colour ramp (user choice - straight clones would leave 9 codes
      sharing #CF5870): migmatites light (Patch) -> dark (Diatexite),
      granite gneisses terracotta, garnetite garnet-toned.
    - TLTP Description reconciled to "TLTP - Transported Pisoliths"
      (the QML/SLD labels already said so; the lookup said "Pisoliths").

Fids append 273-283 (UUID is the stable key; '4 - Basemap' has 0
features, so nothing migrates). Table UUIDs, category uuids and symbol
layer ids are deterministic uuid5 so re-runs are stable. Symbols
allocate names 282-292 (max in use 281).

Idempotent and re-runnable: each edit group (1 rename, 1 TLTP fix, 11
rows, 11 categories, 11 symbols, 11 SLD rules) must be exactly 0 or its
full count, anything else aborts without writing.

Usage:  python scripts/inject_basemap_new_lith_codes.py [path\\to\\gpkg]
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

RENAME_FID = 71
RENAME_UUID = "68955728-ae0b-48cd-999a-1994388d2710"
OLD_CODE = "HSPG"
NEW_CODE = "HPPG"
NEW_DESC = "HPPG - Semi-Pelitic Gneiss"

TLTP_DESC_FROM = "TLTP - Pisoliths"
TLTP_DESC_TO = "TLTP - Transported Pisoliths"

FIRST_FID = 273     # current max(fid) = 272
FIRST_SYMBOL = 282  # current max renderer symbol name = 281

# code, Type, description (stored/labelled as "CODE - desc"), clone source
# code, fill RGB. Order fixes fid and symbol allocation - do not reorder.
NEW_CODES = [
    ("TDLP", "Transported Cover", "Duricrust of Transported Pisoliths",
     "RDLP", (255, 239, 219)),
    ("FPGS", "Lithology", "Felsic Pegmatite, Spodumene-bearing",
     "FPG", (247, 155, 184)),
    ("HGT", "Lithology", "Garnetite (>75% gt)", "ZGT", (160, 69, 90)),
    ("HGG", "Lithology", "Granite Gneiss", "HFG", (217, 106, 78)),
    ("HGGA", "Lithology", "Granite Augen Gneiss", "HFG", (227, 135, 111)),
    ("HMID", "Lithology", "Diatexite Migmatite (>25% pmelt)",
     "HMI", (175, 58, 88)),
    ("HMIM", "Lithology", "Metatexite Migmatite (<25% pmelt)",
     "HMI", (201, 86, 114)),
    ("HMIT", "Lithology", "Net Migmatite", "HMI", (216, 113, 138)),
    ("HMIN", "Lithology", "Nebulitic Migmatite", "HMI", (232, 159, 176)),
    ("HMIS", "Lithology", "Stromatic Migmatite", "HMI", (224, 136, 157)),
    ("HMIP", "Lithology", "Patch Migmatite", "HMI", (240, 182, 195)),
]
EXPECT_ROWS_AFTER = 283
EXPECT_CATS_AFTER = 284   # 283 codes + NULL catch-all
EXPECT_RULES_AFTER = 285  # SLD had 274 rules (one spare beyond categories)


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
    row = cur.execute(
        f"SELECT Code, Description, UUID FROM {TABLE} WHERE fid=?",
        (RENAME_FID,)).fetchone()
    if not row:
        bail(f"fid {RENAME_FID} missing")
    if row[2] != RENAME_UUID:
        bail(f"fid {RENAME_FID} UUID {row[2]!r} != expected (wrong row!)")
    fid213 = cur.execute(
        f"SELECT Code FROM {TABLE} WHERE fid=213").fetchone()
    if not fid213 or fid213[0] not in ("ZI",):
        bail(f"fid 213 is {fid213!r}, expected ZI - table shape changed")

    rename_needed = row[0] == OLD_CODE
    if not rename_needed and row[0] != NEW_CODE:
        bail(f"fid {RENAME_FID} code is {row[0]!r}, neither "
             f"{OLD_CODE!r} nor {NEW_CODE!r}")

    existing = {c for (c,) in cur.execute(
        f"SELECT Code FROM {TABLE} WHERE Code IN (%s)"
        % ",".join("?" * len(NEW_CODES)), [c[0] for c in NEW_CODES])}
    if existing and len(existing) != len(NEW_CODES):
        bail(f"partial code state: {sorted(existing)} already present")
    inserts_needed = not existing

    tltp = cur.execute(
        f"SELECT Description FROM {TABLE} WHERE Code='TLTP'").fetchone()
    if not tltp:
        bail("TLTP row missing")
    tltp_needed = tltp[0] == TLTP_DESC_FROM
    if not tltp_needed and tltp[0] != TLTP_DESC_TO:
        bail(f"TLTP description unexpected: {tltp[0]!r}")

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

    # -- QML rename (0 or 1) --
    qml_rename_needed = f'value="{OLD_CODE}"' in renderer
    if qml_rename_needed:
        cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % OLD_CODE, renderer)
        old_cat = cm.group(0)
        new_cat = old_cat.replace(f'value="{OLD_CODE}"', f'value="{NEW_CODE}"')
        new_cat = re.sub(r'label="[^"]*"', f'label="{NEW_DESC}"', new_cat)
        renderer = renderer.replace(old_cat, new_cat)
        print(f"category {OLD_CODE} -> {NEW_CODE}")
    elif f'value="{NEW_CODE}"' not in renderer:
        bail(f"neither {OLD_CODE!r} nor {NEW_CODE!r} category present")

    # -- QML categories + symbols (0 or 11) --
    present = [c for c, *_ in NEW_CODES if f'value="{c}"' in renderer]
    if present and len(present) != len(NEW_CODES):
        bail(f"partial category state: {present}")
    cats_needed = not present
    if cats_needed:
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

    # -- SLD rename (0 or 1) --
    sld_rename_needed = sld_rule_for(sld, OLD_CODE) is not None
    if sld_rename_needed:
        m = sld_rule_for(sld, OLD_CODE)
        sld = (sld[:m.start()] + m.group(0).replace(OLD_CODE, NEW_CODE)
               + sld[m.end():])
        print(f"SLD rule {OLD_CODE} -> {NEW_CODE}")
    elif sld_rule_for(sld, NEW_CODE) is None:
        bail(f"neither {OLD_CODE!r} nor {NEW_CODE!r} SLD rule present")

    # -- SLD new rules (0 or 11) --
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

    groups = [rename_needed, qml_rename_needed, sld_rename_needed,
              inserts_needed, cats_needed, sld_needed, tltp_needed]
    if not any(groups):
        print("already applied (no change)")
    else:
        if len({rename_needed, qml_rename_needed, sld_rename_needed}) != 1:
            bail("rename state differs between table/QML/SLD")
        if len({inserts_needed, cats_needed, sld_needed}) != 1:
            bail("insert state differs between table/QML/SLD")
        # Validate BEFORE writing: never persist styles that no longer parse.
        try:
            ET.fromstring(new_qml)
            ET.fromstring(sld)
        except ET.ParseError as exc:
            bail(f"edited style no longer parses, aborting without write: {exc}")

        if rename_needed:
            cur.execute(f"UPDATE {TABLE} SET Code=?, Description=? WHERE fid=?",
                        (NEW_CODE, NEW_DESC, RENAME_FID))
            assert cur.rowcount == 1
        if tltp_needed:
            cur.execute(f"UPDATE {TABLE} SET Description=? WHERE Code='TLTP'",
                        (TLTP_DESC_TO,))
            assert cur.rowcount == 1
            print(f"TLTP description -> {TLTP_DESC_TO!r}")
        if inserts_needed:
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
    assert cur.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE Code=?",
                       (OLD_CODE,)).fetchone()[0] == 0
    code, u = cur.execute(f"SELECT Code, UUID FROM {TABLE} WHERE fid=?",
                          (RENAME_FID,)).fetchone()
    assert code == NEW_CODE and u == RENAME_UUID
    assert cur.execute(f"SELECT Code FROM {TABLE} WHERE fid=213"
                       ).fetchone()[0] == "ZI"
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
    assert OLD_CODE not in values
    for code, _t, desc, _s, _rgb in NEW_CODES + [(NEW_CODE, 0, 0, 0, 0)]:
        assert values.count(code) == 1, code
    assert "NULL" in values
    sym_names = {s.get("name") for s in renderer_el.find("symbols")}
    for i in range(len(NEW_CODES)):
        assert str(FIRST_SYMBOL + i) in sym_names, FIRST_SYMBOL + i
    assert "FilterExpression" in final_qml  # ValueRelation config survives
    rules = re.findall(r'<se:Rule>', final_sld)
    assert len(rules) == EXPECT_RULES_AFTER, len(rules)
    assert f"<ogc:Literal>{OLD_CODE}</ogc:Literal>" not in final_sld
    for code, *_ in NEW_CODES:
        assert final_sld.count(f"<ogc:Literal>{code}</ogc:Literal>") == 1, code
    print("round-trip ok: 283 codes, 284 categories, 285 SLD rules, "
          "rename complete, fid 213 untouched")
    con.close()


if __name__ == "__main__":
    main()
