"""Linework restyle: formline dash density, length ordering, axial dash-dot.

Three cartographic fixes to the '2 - Linework' categorized renderer
(attr="Type", reference scale 5000):

    - Formlines (8 categories: Formline, Formline - S0, - S0 (Younging
      Known), - S1..S5): customdash 4;4 -> 4;2 Point (half the gap, so
      tightly curved lines keep their curve detail) and
      tweak_dash_pattern_on_corners 0 -> 1 (dashes land on curve
      vertices). Foliation Trend is pixel-identical to Formline today and
      deliberately stays 4;4 (user decision) - which is why categories
      are matched BY VALUE, never by dash signature (4;4 is also the NULL
      fallback's dash).
    - Feature rendering order: enableorderby 0 -> 1 + an <orderby>
      $length descending clause (longest lines drawn first/bottom,
      shortest on top) - the Basemap $area house pattern applied to
      lines. LGS projects are projected mine grids, so $length is planar.
    - Fold Axial Trace - F1..F5: capstyle square -> round (a short dash
      segment with square caps renders as a fat square blob; round caps
      make dots read as circles - the Metamorphic Isograd idiom) and
      customdash 30;10 -> generation-coded dash-dot: Fn = 22-dash then n
      0.5-dots, 7-gaps. Round caps overhang each segment end by half the
      1.46 width (~0.73), so the 7 gap keeps ~5.5 visible and a 0.5 dot
      renders as a ~2 Point circle. Fold Axial Trace - Inferred keeps
      12;6.

line_width is never touched, so inject_weight_scaling.py needs no re-run
(it never scales customdash/capstyle; the Weight dash ramp lives in
inject_dash_weight_scaling.py, whose dd ELSE mirrors these statics - so
re-run THAT after changing any customdash here).

Idempotent and re-runnable: each edit group (8 formlines / 5 axial / 1
orderby) must be exactly 0 (already applied) or its full count, anything
else aborts without writing. Edited symbol blocks are ET round-tripped,
which normalises their whitespace on first run - semantics are unchanged
and validated.

Usage:  python scripts/inject_linework_dash_order.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "2 - Linework"

FORMLINE_VALUES = [
    "Formline",
    "Formline - S0",
    "Formline - S0 (Younging Known)",
    "Formline - S1",
    "Formline - S2",
    "Formline - S3",
    "Formline - S4",
    "Formline - S5",
]
FORMLINE_DASH_FROM = "4;4"
FORMLINE_DASH_TO = "4;2"

AXIAL_DASH_FROM = "30;10"
AXIAL_DASH = "22;7" + ";0.5;7" * 1  # F1; Fn appends further ;0.5;7 pairs
AXIAL_VALUES = {  # value -> target customdash (Fn = 22-dash + n dots)
    "Fold Axial Trace - F%d" % n: "22;7" + ";0.5;7" * n for n in range(1, 6)
}

# Untouched-by-design sentinels, re-checked after write.
UNTOUCHED_DASHES = {
    "Foliation Trend": "4;4",
    "Fold Axial Trace - Inferred": "12;6",
}

ORDERBY_XML = ('<orderby>\n   '
               '<orderByClause nullsFirst="0" asc="0">$length</orderByClause>'
               '\n  </orderby>')


def bail(msg):
    raise SystemExit("ABORT: " + msg)


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


def direct_opts(layer_el):
    """The layer's OWN options - never descend into pattern sub-symbols."""
    cont = layer_el.find("Option")
    if cont is None:
        return {}
    return {o.get("name"): o for o in cont.findall("Option")}


def symbol_for_value(qml, value):
    cm = re.search(r'<category[^>]*value="%s"[^>]*/>' % re.escape(value), qml)
    if not cm:
        bail(f"Linework category {value!r} not found")
    return re.search(r'symbol="(\d+)"', cm.group(0)).group(1)


def the_simple_line(value, sym_el):
    lines = [l for l in sym_el.findall("layer") if l.get("class") == "SimpleLine"]
    if len(lines) != 1:
        bail(f"{value!r}: expected exactly one SimpleLine, found {len(lines)}")
    return lines[0]


def set_opt(opts, name, want, allowed_from, value):
    """Set an option to want; returns True if edited, bails off-convention."""
    opt = opts.get(name)
    if opt is None:
        bail(f"{value!r}: option {name!r} not found")
    have = opt.get("value")
    if have == want:
        return False
    if have not in allowed_from:
        bail(f"{value!r}: unexpected {name} {have!r}")
    opt.set("value", want)
    return True


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail(f"no styleQML for {LAYER!r}")
    qml = row[0]

    # --- Edit A: formline dash density -------------------------------
    formline_edits = 0
    for value in FORMLINE_VALUES:
        sym = symbol_for_value(qml, value)
        s, e = symbol_block(qml, sym)
        sym_el = ET.fromstring(qml[s:e])
        opts = direct_opts(the_simple_line(value, sym_el))
        edited = set_opt(opts, "customdash", FORMLINE_DASH_TO,
                         (FORMLINE_DASH_FROM,), value)
        edited |= set_opt(opts, "tweak_dash_pattern_on_corners", "1",
                          ("0",), value)
        if edited:
            qml = qml[:s] + ET.tostring(sym_el, encoding="unicode") + qml[e:]
            formline_edits += 1
            print(f"{value}: dash -> {FORMLINE_DASH_TO}, corner tweak on")
    if formline_edits not in (0, len(FORMLINE_VALUES)):
        bail(f"partial formline state: {formline_edits} of {len(FORMLINE_VALUES)}")

    # --- Edit B: axial trace dash-dot hierarchy ----------------------
    axial_edits = 0
    for value, dash in AXIAL_VALUES.items():
        sym = symbol_for_value(qml, value)
        s, e = symbol_block(qml, sym)
        sym_el = ET.fromstring(qml[s:e])
        opts = direct_opts(the_simple_line(value, sym_el))
        edited = set_opt(opts, "customdash", dash, (AXIAL_DASH_FROM,), value)
        edited |= set_opt(opts, "capstyle", "round", ("square",), value)
        if edited:
            qml = qml[:s] + ET.tostring(sym_el, encoding="unicode") + qml[e:]
            axial_edits += 1
            print(f"{value}: dash -> {dash}, cap round")
    if axial_edits not in (0, len(AXIAL_VALUES)):
        bail(f"partial axial state: {axial_edits} of {len(AXIAL_VALUES)}")

    # --- Edit C: length-descending feature order ---------------------
    rm = re.search(r'<renderer-v2\b[^>]*>', qml)
    if not rm:
        bail("renderer-v2 tag not found")
    tag = rm.group(0)
    order_edits = 0
    if 'enableorderby="0"' in tag:
        if "<orderby>" in qml:
            bail("enableorderby off but an <orderby> block exists")
        qml = (qml[:rm.start()]
               + tag.replace('enableorderby="0"', 'enableorderby="1"')
               + qml[rm.end():])
        close = qml.index("</renderer-v2>", rm.start())
        qml = qml[:close] + ORDERBY_XML + "\n " + qml[close:]
        order_edits = 1
        print("renderer: orderby $length descending enabled")
    elif 'enableorderby="1"' not in tag:
        bail("renderer-v2 has no enableorderby attribute")

    if formline_edits + axial_edits + order_edits == 0:
        print("already applied (no change)")
    else:
        # Validate BEFORE writing: never persist a QML that no longer parses.
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail(f"edited QML no longer parses, aborting without write: {exc}")
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print(f"styleQML updated: {formline_edits} formlines, "
              f"{axial_edits} axial traces, orderby={bool(order_edits)}")

    # Validate: gpkg intact, QML parses, every edit and sentinel exact.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    final = cur.fetchone()[0]
    ET.fromstring(final)
    print(f"QML parses: {LAYER}")

    def line_opts_for(value):
        s, e = symbol_block(final, symbol_for_value(final, value))
        sym_el = ET.fromstring(final[s:e])
        return {name: o.get("value") for name, o
                in direct_opts(the_simple_line(value, sym_el)).items()}

    for value in FORMLINE_VALUES:
        opts = line_opts_for(value)
        assert opts["customdash"] == FORMLINE_DASH_TO, (value, opts["customdash"])
        assert opts["tweak_dash_pattern_on_corners"] == "1", value
        assert opts["capstyle"] == "square", value  # formlines keep square
    for value, dash in AXIAL_VALUES.items():
        opts = line_opts_for(value)
        assert opts["customdash"] == dash, (value, opts["customdash"])
        assert opts["capstyle"] == "round", value
        assert opts["line_width"] == "1.46", value  # weight-scaling base intact
    for value, dash in UNTOUCHED_DASHES.items():
        opts = line_opts_for(value)
        assert opts["customdash"] == dash, (value, opts["customdash"])
    rend = re.search(r'<renderer-v2\b[^>]*>', final).group(0)
    assert 'enableorderby="1"' in rend, rend
    assert 'type="categorizedSymbol"' in rend and 'attr="Type"' in rend, rend
    assert 'referencescale="5000"' in rend, rend
    clauses = re.findall(r'<orderByClause[^>]*>([^<]*)</orderByClause>', final)
    assert clauses == ["$length"], clauses
    assert final.count("<orderby>") == 1
    print("round-trip ok: formline dash, axial dash-dot hierarchy, "
          "orderby $length, sentinels untouched")
    con.close()


if __name__ == "__main__":
    main()
