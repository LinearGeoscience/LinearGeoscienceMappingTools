"""Give a duplicated or split feature a UUID of its own.

Duplicating a line or polygon is the quick way to add another feature that
shares most of its attributes - but QGIS copies every attribute verbatim,
UUID included, so the copy arrives wearing the original's identity. Nothing
downstream expects that: the importer matches on UUID and drops the copy as
"already there", and reconcile silently drops duplicate UUIDs on merge.

QGIS >= 3.34 lets a field say what should happen to it on duplicate and on
split. The template already carries the policy blocks and the
uuid('WithoutBraces') default; all that is missing is pointing UUID's
policies at that default instead of at the old value:

    <duplicatePolicies> <policy policy="Duplicate" field="UUID"/>
    <splitPolicies>     <policy policy="Duplicate" field="UUID"/>
                                    -> policy="DefaultValue"

The four mapping layers are done together. FieldNotebook's split policy is
already DefaultValue and is left alone.

QField's own Duplicate button may not honour the field policy - the importer
flags and re-UUIDs repeated values as the backstop either way.

Idempotent and re-runnable.

Usage:  python scripts/inject_uuid_duplicate_policy.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

LAYERS = ('1 - FieldNotebook', '2 - Linework', '3 - Overlay', '4 - Basemap')

# The policy blocks each hold one <policy> per field, so the swap is scoped to
# a block first and matched on field="UUID" exactly - '4 - Basemap' also
# carries stale lowercase 'uuid' entries for a column that no longer exists.
BLOCKS = ('duplicatePolicies', 'splitPolicies')
FIELD = 'UUID'
WANTED = 'DefaultValue'


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def set_policy(qml, block, field, wanted):
    """Point one field's policy inside one block at `wanted`.

    Returns (qml, changed). Bails when the block or the field is missing:
    a silent no-op would look identical to "already applied".
    """
    match = re.search(r'<{0}>.*?</{0}>'.format(block), qml, re.S)
    if not match:
        bail("<{0}> block not found".format(block))
    body = match.group(0)
    tag = re.search(r'<policy\b[^>]*field="{0}"[^>]*/>'.format(re.escape(field)),
                    body)
    if not tag:
        bail("no {0} policy for {1!r}".format(block, field))
    current = re.search(r'policy="([^"]*)"', tag.group(0))
    if current and current.group(1) == wanted:
        return qml, False
    fixed = re.sub(r'policy="[^"]*"', 'policy="{0}"'.format(wanted),
                   tag.group(0), count=1)
    body = body[:tag.start()] + fixed + body[tag.end():]
    return qml[:match.start()] + body + qml[match.end():], True


def main():
    default = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail("gpkg not found: {0}".format(gpkg))
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    for layer in LAYERS:
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        row = cur.fetchone()
        if not row or not row[0]:
            bail("no styleQML for {0!r}".format(layer))
        qml = row[0]
        changed = False

        for block in BLOCKS:
            qml, did = set_policy(qml, block, FIELD, WANTED)
            changed = changed or did
            print("{0} {1}: {2}".format(
                layer, block, "set to " + WANTED if did else "already applied"))

        # Validate BEFORE writing: never persist a QML that no longer parses.
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail("edited QML no longer parses, aborting without write: "
                 "{0}".format(exc))

        if changed:
            cur.execute(
                "UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (qml, layer))
            assert cur.rowcount == 1
            con.commit()

    # Validate: gpkg intact, every QML parses, both policies round-trip, and
    # the default the policies now lean on is still there.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    for layer in LAYERS:
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        root = ET.fromstring(cur.fetchone()[0])
        for block in BLOCKS:
            element = root.find(block)
            assert element is not None, "{0}: no <{1}>".format(layer, block)
            policy = next((p for p in element.findall('policy')
                           if p.get('field') == FIELD), None)
            assert policy is not None, "{0}: no {1} for UUID".format(layer, block)
            assert policy.get('policy') == WANTED, \
                "{0} {1}: {2}".format(layer, block, policy.get('policy'))
        default = next((d for d in root.iter('default')
                        if d.get('field') == FIELD), None)
        assert default is not None and 'uuid(' in (default.get('expression') or ''), \
            "{0}: UUID default expression missing".format(layer)
        print("round-trip ok: {0}".format(layer))
    con.close()


if __name__ == "__main__":
    main()
