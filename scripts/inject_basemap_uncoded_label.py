"""Basemap: UncodedLithology label override + remove the Float field.

Two changes to "4 - Basemap" in the template:

    1. Label expression: when UncodedLithology is filled it becomes the
       ENTIRE polygon label (user decision); otherwise the existing
       coded Lithology1/Lithology2 lines render as before.
    2. The Float field is removed outright - the "(Subcrop)" label line
       it drove, every styleQML reference (form placement, edit widget,
       alias/default/constraint/policy/attribute-table entries), and the
       column itself (ALTER TABLE DROP COLUMN; refuses to run if any row
       actually carries a Float value).

Nothing in the plugin regenerates Basemap labeling or style, so the
template is the single home of this config.

SUPERSEDED for the label expression by inject_basemap_lith_modifiers.py
(which builds the current label including mineral/texture modifiers) -
do NOT re-run this script, it would regress the label.

Idempotent and re-runnable; the QML is validated with ElementTree BEFORE
anything is written.

Usage:  python scripts/inject_basemap_uncoded_label.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYER = "4 - Basemap"

LABEL_EXPR = (
    "-- Uncoded lithology override: free-text lithology becomes the whole label\r\n"
    "case \r\n"
    "  when coalesce(\"UncodedLithology\",'') != '' then\r\n"
    "    '<div>' || \"UncodedLithology\" || '</div>'\r\n"
    "  else\r\n"
    "\r\n"
    "-- Lithology 1 line (includes prefix and symbol)\r\n"
    "case \r\n"
    "  when coalesce(\"Lithology1\",'') != '' then\r\n"
    "    '<div>' ||\r\n"
    "      coalesce(\"Sulphides/Mineralisation\",'') ||\r\n"
    "      case \r\n"
    "        when coalesce(\"LithologyPrefix\",'') != '' \r\n"
    "          then ' ' || \"LithologyPrefix\" || '-' \r\n"
    "        else '' \r\n"
    "      end ||\r\n"
    "      \"Lithology1\" ||\r\n"
    "      case \r\n"
    "        when coalesce(\"Lith1Feature\",'') != '' \r\n"
    "          then ' <span style=\"font-style:italic;font-size:70%;\">('"
    " || \"Lith1Feature\" || ')</span>'\r\n"
    "        else '' \r\n"
    "      end ||\r\n"
    "    '</div>'\r\n"
    "  else '' \r\n"
    "end ||\r\n"
    "\r\n"
    "-- Lithology 2 + feature\r\n"
    "case \r\n"
    "  when coalesce(\"Lithology2\",'') != '' then\r\n"
    "    '<div>' || \"Lithology2\" ||\r\n"
    "    case \r\n"
    "      when coalesce(\"Lith2Feature\",'') != '' \r\n"
    "        then ' <span style=\"font-style:italic;font-size:70%;\">('"
    " || \"Lith2Feature\" || ')</span>'\r\n"
    "      else '' \r\n"
    "    end || '</div>'\r\n"
    "  else '' \r\n"
    "end\r\n"
    "\r\n"
    "  end\r\n"
)

# Every Float reference in the styleQML is a self-contained tag/block.
FLOAT_PATTERNS = [
    re.compile(r'<attributeEditorField\b[^>]*name="Float".*?</attributeEditorField>', re.S),
    re.compile(r'<field name="Float" configurationFlags[^>]*>.*?</field>', re.S),
    re.compile(r'<alias [^>]*field="Float"[^>]*/>'),
    re.compile(r'<policy [^>]*field="Float"[^>]*/>'),
    re.compile(r'<default [^>]*field="Float"[^>]*/>'),
    re.compile(r'<constraint [^>]*field="Float"[^>]*/>'),
    re.compile(r'<column name="Float"[^>]*/>'),
    re.compile(r'<field name="Float" editable[^>]*/>'),
    re.compile(r'<field name="Float" labelOnTop[^>]*/>'),
    re.compile(r'<field reuseLastValue="0" name="Float"[^>]*/>'),
]


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


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

    # 1. Label expression: UncodedLithology override, Subcrop line gone.
    m = re.search(r'<labeling type="simple">.*?</labeling>', qml, re.S)
    if not m:
        bail("simple <labeling> block not found")
    lab = ET.fromstring(m.group(0))
    ts = lab.find(".//text-style")
    if ts is None:
        bail("<text-style> not found in labeling block")
    if ts.get("fieldName") == LABEL_EXPR:
        print("label expression: already applied")
    else:
        ts.set("fieldName", LABEL_EXPR)
        qml = qml[:m.start()] + ET.tostring(lab, encoding="unicode") + qml[m.end():]
        print("label expression: UncodedLithology override injected")

    # 2. Scrub Float from the styleQML (exact-span removals).
    removed = 0
    for pat in FLOAT_PATTERNS:
        qml, n = pat.subn("", qml)
        removed += n
    print(f"Float styleQML references removed: {removed}"
          if removed else "Float styleQML references: already removed")
    for leftover in re.finditer(r'[^>]*(?:name|field)="Float"', qml):
        bail(f"unexpected Float reference survived: {leftover.group(0)[-120:]!r}")

    # Validate BEFORE writing: never persist a QML that no longer parses.
    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses, aborting without write: {exc}")

    if qml != row[0]:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()
        print("styleQML updated")

    # 3. Drop the Float column (guarded).
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{LAYER}")')]
    if "Float" not in cols:
        print("Float column: already dropped")
    else:
        n = cur.execute(
            f'SELECT COUNT(*) FROM "{LAYER}" '
            'WHERE "Float" IS NOT NULL AND "Float" != \'\'').fetchone()[0]
        if n:
            bail(f"refusing to drop: {n} feature(s) carry a Float value")
        cur.execute(f'ALTER TABLE "{LAYER}" DROP COLUMN "Float"')
        if cur.execute("SELECT name FROM sqlite_master WHERE type='table' "
                       "AND name='gpkg_data_columns'").fetchone():
            cur.execute("DELETE FROM gpkg_data_columns "
                        "WHERE table_name=? AND column_name='Float'", (LAYER,))
        con.commit()
        print("Float column: dropped")

    # Validate: gpkg intact, QML parses, everything round-trips.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?", (LAYER,))
    final = cur.fetchone()[0]
    root = ET.fromstring(final)
    print(f"QML parses: {LAYER}")
    ts = root.find(".//labeling/settings/text-style")
    assert ts is not None and ts.get("fieldName") == LABEL_EXPR, \
        "label expression round-trip failed"
    assert '"Float"' not in ts.get("fieldName")
    assert not re.search(r'(?:name|field)="Float"', final), "Float refs remain"
    renderer = root.find(".//renderer-v2")
    assert renderer.get("type") == "categorizedSymbol"
    assert renderer.get("attr") == "Lithology1"
    n_cats = len(renderer.find("categories"))
    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{LAYER}")')]
    assert "Float" not in cols and "UncodedLithology" in cols
    print(f"round-trip ok: label expression, Float fully removed, "
          f"renderer untouched ({n_cats} categories)")
    con.close()


if __name__ == "__main__":
    main()
