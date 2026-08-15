"""SampleTypeCodes lookup table + ValueRelation widget on SampleType.

UG paper-mapping parity: sampling pairs with mapping (face/channel
samples with grade notes), but 1 - FieldNotebook's SampleType was free
text.  Adds a lookup table with the user-approved field + UG + QAQC set
and switches the widget to a ValueRelation (AllowNull; the column stays
TEXT so legacy free-text values survive).

Idempotent and re-runnable; QML parse-validated BEFORE writing.

Usage:  python scripts/inject_sampletype_codes.py [path\\to\\gpkg]
"""
import os
import re
import sqlite3
import sys
import uuid
import xml.etree.ElementTree as ET

LAYER = "1 - FieldNotebook"
TABLE = "SampleTypeCodes"

CODES = [
    "Grab", "Rock Chip", "Channel", "Face Chip", "Chip-Channel",
    "Muck/Grade Control", "Float", "Soil", "Stream Sediment", "Core",
    "Whole Rock", "Petrology", "Duplicate", "Standard/Blank",
]


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def opt(parent, name, otype=None, value=None):
    e = ET.SubElement(parent, "Option")
    e.set("name", name)
    if otype is not None:
        e.set("type", otype)
    if value is not None:
        e.set("value", value)
    return e


def widget_block(gpkg_path):
    root = ET.Element("field")
    root.set("name", "SampleType")
    root.set("configurationFlags", "NoFlag")
    ew = ET.SubElement(root, "editWidget")
    ew.set("type", "ValueRelation")
    cfg = ET.SubElement(ew, "config")
    m = ET.SubElement(cfg, "Option")
    m.set("type", "Map")
    opt(m, "AllowMulti", "bool", "false")
    opt(m, "AllowNull", "bool", "true")
    opt(m, "CompleterMatchFlags", "int", "2")
    opt(m, "Description", "invalid")
    opt(m, "DisplayGroupName", "bool", "false")
    opt(m, "FilterExpression", "invalid")
    opt(m, "Group", "invalid")
    opt(m, "Key", "QString", "Code")
    opt(m, "LayerName", "QString", TABLE)
    opt(m, "LayerProviderName", "QString", "ogr")
    opt(m, "LayerSource", "QString",
        gpkg_path.replace("\\", "/") + "|layername=" + TABLE)
    opt(m, "NofColumns", "int", "1")
    opt(m, "OrderByValue", "bool", "true")
    opt(m, "UseCompleter", "bool", "false")
    opt(m, "Value", "QString", "Description")
    return ET.tostring(root, encoding="unicode")


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    # 1. Lookup table + registration.
    if cur.execute("SELECT name FROM sqlite_master WHERE name=?",
                   (TABLE,)).fetchone():
        print(f"{TABLE}: already exists")
    else:
        cur.execute(f'CREATE TABLE "{TABLE}" ("fid" INTEGER PRIMARY KEY '
                    'AUTOINCREMENT NOT NULL, "Code" TEXT, "Description" TEXT, '
                    '"UUID" TEXT(36))')
        for i, code in enumerate(CODES):
            cur.execute(f'INSERT INTO "{TABLE}" (fid, Code, Description, UUID) '
                        "VALUES (?,?,?,?)",
                        (i + 1, code, code,
                         str(uuid.uuid5(uuid.NAMESPACE_URL,
                                        "lgs-sampletype:" + code))))
        print(f"{TABLE}: created with {len(CODES)} codes")
    if not cur.execute("SELECT 1 FROM gpkg_contents WHERE table_name=?",
                       (TABLE,)).fetchone():
        cur.execute("INSERT INTO gpkg_contents (table_name, data_type, "
                    "identifier, description, last_change) VALUES "
                    "(?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (TABLE, "attributes", TABLE, ""))
        print("gpkg_contents: registered")
    else:
        print("gpkg_contents: already registered")
    con.commit()

    # 2. Widget swap.
    qml, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                       (LAYER,)).fetchone()
    original = qml
    m = re.search(r'<field name="SampleType" configurationFlags.*?</field>',
                  qml, re.S)
    if not m:
        bail("SampleType field config not found")
    if 'type="ValueRelation"' in m.group(0):
        print("SampleType widget: already ValueRelation")
    else:
        qml = qml[:m.start()] + widget_block(gpkg) + qml[m.end():]
        print("SampleType widget: TextEdit -> ValueRelation")

    try:
        ET.fromstring(qml)
    except ET.ParseError as exc:
        bail(f"edited QML no longer parses: {exc}")
    if qml != original:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, LAYER))
        assert cur.rowcount == 1
        con.commit()

    # 3. Validation.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    assert cur.execute(f'SELECT COUNT(*) FROM "{TABLE}"').fetchone()[0] == len(CODES)
    assert cur.execute("SELECT data_type FROM gpkg_contents WHERE table_name=?",
                       (TABLE,)).fetchone() == ("attributes",)
    q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                     (LAYER,)).fetchone()
    root = ET.fromstring(q)
    ew = next(fl.find("editWidget") for fl in root.find("fieldConfiguration")
              if fl.get("name") == "SampleType")
    assert ew.get("type") == "ValueRelation"
    opts = {o.get("name"): o.get("value") for o in ew.iter("Option")}
    assert opts.get("LayerName") == TABLE and opts.get("Key") == "Code"
    print(f"round-trip ok: {len(CODES)} sample types, ValueRelation widget")
    con.close()


if __name__ == "__main__":
    main()
