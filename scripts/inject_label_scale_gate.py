"""Turn labels off once the view is far enough back from the mapping scale.

Rounds 1 and 2 of the label work fixed how lettering LOOKS at any zoom. They
did nothing about when it appears, and the growth band made that worse:
inject_label_size_scaling.PAPER_F clamps the text at GROWTH_FLOOR on the way
out, so it settles at 0.85x its authored size and stays there. Pull back to
1:250,000 on a 1:5000 project and every label it has ever had is still drawn,
still perfectly legible, in a solid mat of text.

Nothing else was going to stop it. minFeatureSize takes the reference-scale
multiplier itself, so its 2 mm threshold SHRINKS as you zoom out and it gets
less selective, not more.

So each labeling gets scale-based visibility, with the cutoff data-defined off
the project's mapping scale rather than written as a fixed number - a ratio
works at 1:500 underground and 1:250,000 regional without reconfiguration, the
same argument that moved the lithology texture gate into renderer_compat.

    1 - FieldNotebook   5x   (the four drawing rules, not the root settings)
    2 - Linework        5x, but 10x for Major and Regional
    3 - Overlay         5x
    4 - Basemap         5x

Three things about the mechanism, each of which cost a measurement:

- It has to be MinimumScale. The dd 'Show' property is already bound to
  auxiliary_storage_labeling_show on Linework and Overlay - that is QGIS'
  per-label hand-hide toggle, and an expression there would silently take
  away the geologist's ability to hide a single label.
- MinimumScale holds the LARGER denominator despite the name; QGIS names
  these for the view, so the "minimum" scale is the most zoomed-OUT one still
  shown. Setting the API's minimumScale = 25000 serialises as QML
  scaleMax="25000". Writing it to MaximumScale gives an empty range and no
  labels anywhere - the same inversion that once cost the textures.
- scaleVisibility="1" is only the enable flag. The statics scaleMin/scaleMax
  stay 0, so the data-defined expression is the single source of the number.

Owns, on every labeling it touches: <rendering> scaleVisibility/scaleMin/
scaleMax, and the dd MinimumScale entry. Nothing else wrote those.

Idempotent and re-runnable: the expression is rebuilt from renderer_compat on
every run, never read back and extended.

Usage:  python scripts/inject_label_scale_gate.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from renderer_compat import (LABEL_GATE_RATIO,  # noqa: E402
                             LINEWORK_PERSIST_FACTOR,
                             label_scale_gate_expression)

FIELDNOTEBOOK = "1 - FieldNotebook"
LINEWORK = "2 - Linework"

# The four rules that draw. The rule-based ROOT settings is deliberately not
# gated: script_setmapping.build_structural_labeling() builds that root from a
# bare QgsPalLayerSettings, and test_label_code_template_qgis.py pins template
# == code, so anything baked there and not built there fails the pin.
FIELDNOTEBOOK_RULES = (
    "Dip Labels",
    "SymbolSuffix Labels",
    "Fallback Labels (Comments/Labels)",
    "Regolith Note",
)

SIMPLE_LAYERS = (LINEWORK, "3 - Overlay", "4 - Basemap")

# The dd is the only source of the cutoff; the statics say "no static limit".
RENDERING_ATTRS = {
    "scaleVisibility": "1",
    "scaleMin": "0",
    "scaleMax": "0",
}
DD_NAME = "MinimumScale"

# The geologist's manual label moves, carried in auxiliary storage. Losing one
# is silent and unrecoverable, so they are asserted by name after the write.
AUX_BINDINGS = ("auxiliary_storage_labeling_positionx",
                "auxiliary_storage_labeling_positiony")


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def expression_for(layer):
    return label_scale_gate_expression(persist_major=(layer == LINEWORK))


def inject_dd(settings, name, expr):
    """Set one data-defined property, leaving its siblings alone.

    Same shape as scripts/inject_basemap_label_placement.py's helper: the
    settings-level dd_properties also carries the auxiliary-storage bindings
    and the injected Size/Color entries, so this replaces one named entry and
    never rewrites the block.
    """
    dd = settings.find("dd_properties")
    if dd is None:
        return False
    outer = dd.find("Option")
    if outer is None:
        outer = ET.SubElement(dd, "Option", {"type": "Map"})
    props = None
    for o in outer.findall("Option"):
        if o.get("name") == "properties":
            props = o
    if props is None:
        props = ET.SubElement(outer, "Option", {"name": "properties"})
    props.set("type", "Map")
    props.attrib.pop("value", None)
    for o in props.findall("Option"):
        if o.get("name") == name:
            props.remove(o)
    entry = ET.SubElement(props, "Option", {"name": name, "type": "Map"})
    ET.SubElement(entry, "Option",
                  {"name": "active", "type": "bool", "value": "true"})
    ET.SubElement(entry, "Option",
                  {"name": "expression", "type": "QString", "value": expr})
    ET.SubElement(entry, "Option", {"name": "type", "type": "int", "value": "3"})
    return True


def gate_settings(settings, expr, label):
    """Apply the gate to one <settings> element."""
    rendering = settings.find("rendering")
    if rendering is None:
        bail("%s: <rendering> not found" % label)
    for k, v in RENDERING_ATTRS.items():
        if rendering.get(k) != v:
            rendering.set(k, v)
            print("%s: rendering %s -> %s" % (label, k, v))
    if not inject_dd(settings, DD_NAME, expr):
        bail("%s: settings-level <dd_properties> not found" % label)


def edit_labeling(qml, kind, editor):
    """Run editor() over the layer's <labeling> block; return the new QML."""
    m = re.search(r'<labeling type="%s">.*?</labeling>' % kind, qml, re.S)
    if not m:
        bail("%s <labeling> block not found" % kind)
    lab = ET.fromstring(m.group(0))
    editor(lab)
    new_qml = qml[:m.start()] + ET.tostring(lab, encoding="unicode") + qml[m.end():]
    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(new_qml)
    except ET.ParseError as exc:
        bail("edited QML no longer parses, aborting: %s" % exc)
    return new_qml


def read_qml(cur, layer):
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                (layer,))
    row = cur.fetchone()
    if not row or not row[0]:
        bail("no styleQML for %r" % layer)
    return row[0]


def labeling_block(qml, kind):
    m = re.search(r'<labeling type="%s">.*?</labeling>' % kind, qml, re.S)
    if not m:
        bail("%s <labeling> block not found" % kind)
    return ET.fromstring(m.group(0))


def dd_names(settings):
    dd = settings.find("dd_properties")
    if dd is None:
        return set()
    return {o.get("name") for o in dd.iter("Option") if o.get("name")}


def dd_xml(settings):
    """The dd block as text. The auxiliary-storage bindings are the `field`
    VALUE of an entry, not its name, so they only show up in the serialised
    form - the same check scripts/inject_basemap_label_placement.py makes.
    """
    dd = settings.find("dd_properties")
    return "" if dd is None else ET.tostring(dd, encoding="unicode")


def dd_expression(settings, name):
    dd = settings.find("dd_properties")
    if dd is None:
        return None
    for o in dd.iter("Option"):
        if o.get("name") == name:
            for child in o.findall("Option"):
                if child.get("name") == "expression":
                    return child.get("value")
    return None


def verify(settings, expr, label, survivors=(), check_aux=False):
    rendering = settings.find("rendering")
    for k, v in RENDERING_ATTRS.items():
        assert rendering.get(k) == v, \
            "%s: rendering %s=%r, want %r" % (label, k, rendering.get(k), v)
    got = dd_expression(settings, DD_NAME)
    assert got == expr, "%s: dd %s=%r, want %r" % (label, DD_NAME, got, expr)
    names = dd_names(settings)
    for n in survivors:
        assert n in names, "%s: lost dd entry %r" % (label, n)
    if check_aux:
        # Only the three simple layers carry these; the FieldNotebook rules
        # place their text by OffsetXY off the structural symbol and have
        # never had a manual-move binding to lose.
        xml = dd_xml(settings)
        for n in AUX_BINDINGS:
            assert n in xml,                 "%s: lost the manual label move binding %r" % (label, n)
    print("verified: %s" % label)


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default = os.path.join(repo, "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: %s" % gpkg)
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    print("cutoff = %dx the mapping scale (%dx for Major/Regional linework)"
          % (LABEL_GATE_RATIO, LABEL_GATE_RATIO * LINEWORK_PERSIST_FACTOR))

    # Captured before the edit so the round-trip can prove nothing was lost.
    before = {}

    for layer in SIMPLE_LAYERS:
        qml = read_qml(cur, layer)
        expr = expression_for(layer)
        before[layer] = dd_names(labeling_block(qml, "simple").find("settings"))

        def editor(lab, _expr=expr, _layer=layer):
            settings = lab.find("settings")
            if settings is None:
                bail("%s: <settings> not found" % _layer)
            gate_settings(settings, _expr, _layer)

        new_qml = edit_labeling(qml, "simple", editor)
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (new_qml, layer))
        assert cur.rowcount == 1
        print("%s: dd %s = %s" % (layer, DD_NAME, expr))

    # FieldNotebook: rule-based, four rules, root settings left alone.
    qml = read_qml(cur, FIELDNOTEBOOK)
    fn_expr = expression_for(FIELDNOTEBOOK)
    seen = []

    def fn_editor(lab):
        for rule in lab.iter("rule"):
            desc = rule.get("description")
            settings = rule.find("settings")
            if desc in FIELDNOTEBOOK_RULES and settings is not None:
                gate_settings(settings, fn_expr,
                              "%s/%s" % (FIELDNOTEBOOK, desc))
                seen.append(desc)

    new_qml = edit_labeling(qml, "rule-based", fn_editor)
    missing = set(FIELDNOTEBOOK_RULES) - set(seen)
    if missing:
        bail("%s: rules not found: %s" % (FIELDNOTEBOOK, sorted(missing)))
    cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (new_qml, FIELDNOTEBOOK))
    assert cur.rowcount == 1
    print("%s: dd %s on %d rules" % (FIELDNOTEBOOK, DD_NAME, len(seen)))

    con.commit()
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    # --- Round-trip validation, re-read from the gpkg. ---
    for layer in SIMPLE_LAYERS:
        settings = labeling_block(read_qml(cur, layer), "simple").find("settings")
        verify(settings, expression_for(layer), layer, tuple(before[layer]),
               check_aux=True)

    lab = labeling_block(read_qml(cur, FIELDNOTEBOOK), "rule-based")
    checked = 0
    for rule in lab.iter("rule"):
        if rule.get("description") in FIELDNOTEBOOK_RULES:
            verify(rule.find("settings"), fn_expr,
                   "%s/%s" % (FIELDNOTEBOOK, rule.get("description")))
            checked += 1
    assert checked == len(FIELDNOTEBOOK_RULES), \
        "%s: verified %d of %d rules" % (FIELDNOTEBOOK, checked,
                                         len(FIELDNOTEBOOK_RULES))
    con.close()


if __name__ == "__main__":
    main()
