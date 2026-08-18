"""One lettering system across all four template layers.

Harry's review of the 1:5000 render sheet (2026-08-17) settled four things:

  1. Unit labels go 4 -> 5.5 pt. They were the smallest type on a sheet
     whose whole point is the lithology, and the round-6 SVG textures made
     that worse. Letter spacing deliberately unchanged - bigger, not spread.

  2. The unit CODE carries the weight, its modifiers do not. The label
     already renders as HTML, so the code goes semibold while the
     mineral/texture parenthetical stays light italic. This is what
     replaces the halo: the code separates from the texture because it is
     heavier, not because something was erased behind it. Ink softens from
     pure black to #1A1A1A against the pastel fills.

  3. One family everywhere - Leelawadee UI Semilight, which Linework
     already used. Annotation (Linework) drops 8 -> 6 pt and goes italic,
     so line and zone labels sit below the unit names in the hierarchy.
     NOTE: Windows ships no italic file for this family (LEELAWAD.TTF,
     LEELAWDB.TTF, LeelawUI.ttf only), so Qt synthesises the slant. That
     is what the review sheet rendered and what Harry picked. Because of
     it, namedStyle is cleared wherever the family is set: asking Qt for a
     style name a family does not have can resolve to a DIFFERENT family
     altogether, whereas fontItalic alone gives the synthetic oblique.

  4. Long lines repeat their label every 60 mm. Naming a fault once is a
     limitation, not a style.

And two defects found on the way:

  - No halos, no masks, anywhere (Harry's call). Overlay's 0.6 mm white
    buffer is switched off, and Linework's mask goes with it - that mask
    was inert anyway: maskEnabled=1 with 80 maskedSymbolLayers entries
    naming two symbol-layer IDs that appear NOWHERE in the renderer (whose
    IDs are all {uuid} form). It has been masking nothing.

  - The RegolithNote renderer category was labelled with its raw code
    where every other observation uses its description.

Run scripts/inject_label_size_scaling.py AFTER this one: it re-bakes each
layer's data-defined Size expression from the current static fontSize, so
running it first leaves the multiplier pointing at the old base.

The font family here MUST STAY IN STEP with script_setmapping.LABEL_FONT -
Set Mapping Scale rebuilds the FieldNotebook labeling from that module.
tests/test_label_code_template_qgis.py is the check.

Idempotent and re-runnable; QML parse-validated BEFORE writing.

Usage:  python scripts/inject_label_cartography.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

FONT = "Leelawadee UI Semilight"

LITH_SIZE = "5.5"
LITH_COLOUR = ("26,26,26,255,rgb:0.10196078431372549,"
               "0.10196078431372549,0.10196078431372549,1")
ANNO_SIZE = "6"
REPEAT_MM = "60"

# The label expression's own markup, before and after the weight split.
DIV = "'<div>'"
DIV_BOLD = "'<div style=\"font-weight:600;\">'"
SPAN = "font-style:italic;font-size:70%;"
SPAN_LIGHT = "font-style:italic;font-weight:400;font-size:70%;"
N_DIV = 3    # uncoded override, Lithology1 line, Lithology2 line
N_SPAN = 2   # one modifier parenthetical per lithology line

FIELDNOTEBOOK = "1 - FieldNotebook"
REGOLITH_CODE = "RegolithNote"
REGOLITH_LABEL = "Regolith Note"

# Per layer: the text-style attributes to force, and any placement or
# rendering attributes that go with them.
LAYERS = {
    "4 - Basemap": dict(
        labeling="simple",
        text={"fontFamily": FONT, "namedStyle": "",
              "fontSize": LITH_SIZE, "textColor": LITH_COLOUR},
    ),
    "2 - Linework": dict(
        labeling="simple",
        text={"fontFamily": FONT, "namedStyle": "",
              "fontSize": ANNO_SIZE, "fontItalic": "1"},
        mask={"maskEnabled": "0", "maskedSymbolLayers": ""},
        placement={"repeatDistance": REPEAT_MM, "repeatDistanceUnits": "MM"},
    ),
    "3 - Overlay": dict(
        labeling="simple",
        text={"fontFamily": FONT, "namedStyle": "", "fontItalic": "1"},
        buffer={"bufferDraw": "0"},
    ),
    FIELDNOTEBOOK: dict(
        labeling="rule-based",
        text={"fontFamily": FONT, "namedStyle": ""},
    ),
}


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def set_attrs(elem, attrs, where):
    """Force attrs onto elem, reporting only what actually moved."""
    changed = 0
    for key, value in attrs.items():
        if elem.get(key) != value:
            print(f"  {where}: {key} {elem.get(key)!r} -> {value!r}")
            elem.set(key, value)
            changed += 1
    return changed


def style_blocks(labeling_elem):
    """Yield every (text-style, settings) pair in a labeling block.

    Simple labeling has one; rule-based has one per rule.
    """
    for settings in labeling_elem.iter("settings"):
        text_style = settings.find("text-style")
        if text_style is not None:
            yield text_style, settings


def weight_split(text_style, where):
    """Semibold the unit code, keep its modifiers light."""
    expr = text_style.get("fieldName") or ""
    if DIV_BOLD in expr and SPAN_LIGHT in expr:
        return 0
    if expr.count(DIV) != N_DIV or expr.count(SPAN) != N_SPAN:
        bail(f"{where}: label expression is not in a known state "
             f"({expr.count(DIV)} plain <div>, {expr.count(SPAN)} plain span) "
             f"- has inject_basemap_mineral_pcts.py been re-run since?")
    text_style.set("fieldName",
                   expr.replace(DIV, DIV_BOLD).replace(SPAN, SPAN_LIGHT))
    print(f"  {where}: unit code semibold, modifiers held at regular")
    return 1


def apply_layer(cur, layer, spec):
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                (layer,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail(f"no styleQML for {layer!r}")
    qml = row[0]

    pattern = r'<labeling type="%s">.*?</labeling>' % spec["labeling"]
    match = re.search(pattern, qml, re.S)
    if not match:
        bail(f"{layer}: {spec['labeling']} <labeling> block not found")
    labeling = ET.fromstring(match.group(0))

    changed = 0
    for text_style, settings in style_blocks(labeling):
        where = layer
        changed += set_attrs(text_style, spec["text"], where)
        if "buffer" in spec:
            changed += set_attrs(text_style.find("text-buffer"),
                                 spec["buffer"], where)
        if "mask" in spec:
            changed += set_attrs(text_style.find("text-mask"),
                                 spec["mask"], where)
        if "placement" in spec:
            changed += set_attrs(settings.find("placement"),
                                 spec["placement"], where)
        if layer == "4 - Basemap":
            changed += weight_split(text_style, where)

    new_qml = qml[:match.start()] + ET.tostring(labeling, encoding="unicode") \
        + qml[match.end():]

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(new_qml)
    except ET.ParseError as exc:
        bail(f"{layer}: edited QML no longer parses, aborting: {exc}")

    if new_qml != qml:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (new_qml, layer))
        assert cur.rowcount == 1
    elif not changed:
        print(f"  {layer}: already applied")
    return changed


def relabel_regolith_category(cur):
    """The renderer category label is legend text; every other observation
    shows its description, this one showed its raw code."""
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                (FIELDNOTEBOOK,))
    qml = cur.fetchone()[0]
    old = f'value="{REGOLITH_CODE}" label="{REGOLITH_CODE}"'
    new = f'value="{REGOLITH_CODE}" label="{REGOLITH_LABEL}"'
    # Attribute order differs between QGIS saves, so try both spellings.
    alt_old = f'label="{REGOLITH_CODE}" value="{REGOLITH_CODE}"'
    alt_new = f'label="{REGOLITH_LABEL}" value="{REGOLITH_CODE}"'
    if old in qml:
        qml = qml.replace(old, new)
    elif alt_old in qml:
        qml = qml.replace(alt_old, alt_new)
    else:
        print(f"  {FIELDNOTEBOOK}: RegolithNote category already labelled")
        return 0
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"regolith relabel broke the QML, aborting: {exc}")
    cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (qml, FIELDNOTEBOOK))
    assert cur.rowcount == 1
    print(f"  {FIELDNOTEBOOK}: category label {REGOLITH_CODE!r} -> "
          f"{REGOLITH_LABEL!r}")
    return 1


def verify(cur):
    for layer, spec in LAYERS.items():
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        qml = cur.fetchone()[0]
        ET.fromstring(qml)
        labeling = ET.fromstring(
            re.search(r'<labeling type="%s">.*?</labeling>' % spec["labeling"],
                      qml, re.S).group(0))
        blocks = 0
        for text_style, settings in style_blocks(labeling):
            for key, value in spec["text"].items():
                assert text_style.get(key) == value, \
                    f"{layer}: {key}={text_style.get(key)!r}, want {value!r}"
            for part, finder in (("buffer", lambda t: t.find("text-buffer")),
                                 ("mask", lambda t: t.find("text-mask"))):
                for key, value in spec.get(part, {}).items():
                    got = finder(text_style).get(key)
                    assert got == value, f"{layer}: {key}={got!r}, want {value!r}"
            for key, value in spec.get("placement", {}).items():
                got = settings.find("placement").get(key)
                assert got == value, f"{layer}: {key}={got!r}, want {value!r}"
            blocks += 1
        assert blocks, f"{layer}: no text-style found"
        print(f"  {layer}: {blocks} label block(s) verified")

    # Basemap markup, and nothing left un-split
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                ("4 - Basemap",))
    expr = ET.fromstring(re.search(
        r'<labeling type="simple">.*?</labeling>',
        cur.fetchone()[0], re.S).group(0)).find(
            "settings").find("text-style").get("fieldName")
    assert expr.count(DIV_BOLD) == N_DIV, "unit code not semibold everywhere"
    # At least the two lithology modifier parentheticals, and nothing left
    # in the plain weight.  Not an equality: later injectors legitimately
    # add their own light spans to this label (the vein generation /
    # selvedge tag, inject_vein_generation_selvedge.py), and the invariant
    # here is "nothing un-split", not "exactly two spans exist".
    assert expr.count(SPAN_LIGHT) >= N_SPAN, "modifiers not held at regular"
    assert SPAN not in expr.replace(SPAN_LIGHT, ""), "a plain span survived"
    assert DIV not in expr.replace(DIV_BOLD, ""), "a plain <div> survived"

    # No halo and no mask anywhere in the template
    for layer in LAYERS:
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        qml = cur.fetchone()[0]
        assert 'bufferDraw="1"' not in qml, f"{layer} still draws a buffer"
        assert 'maskEnabled="1"' not in qml, f"{layer} still enables a mask"

    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                (FIELDNOTEBOOK,))
    assert f'label="{REGOLITH_CODE}"' not in cur.fetchone()[0], \
        "RegolithNote category still shows its raw code"


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    if gpkg.endswith("_Patterns.gpkg"):
        bail("that is the generated patterns template - lettering belongs in "
             "the live template; run inject_basemap_lith_patterns.py after")

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    changed = 0
    for layer, spec in LAYERS.items():
        changed += apply_layer(cur, layer, spec)
    changed += relabel_regolith_category(cur)

    if changed:
        con.commit()
        print(f"styleQML updated ({changed} changes)")
    else:
        print("already applied (no change)")

    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    verify(cur)
    print(f"round-trip ok: {FONT} throughout, units {LITH_SIZE} pt with a "
          f"semibold code, annotation {ANNO_SIZE} pt italic, no halo or mask, "
          f"lines repeat every {REPEAT_MM} mm")
    con.close()


if __name__ == "__main__":
    main()
