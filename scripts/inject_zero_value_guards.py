"""Make a recorded value of ZERO render as UNRECORDED (Aug 2026 field fix).

Several data-defined ramps and label expressions test a numeric field with
`IS NULL` / `IS NOT NULL`.  That is right for a field that was never filled
in, but wrong for a stray 0: on a mapped line a width of zero, or a mineral
percentage of zero, is not a reading - it is noise.  Today a 0 lands in the
EXTREME end of every ramp:

    Width_cm  = 0  ->  0.55x stroke (the hairline tier), 0.7x label, '0mm'
    Percent   = 0  ->  the sparsest Overlay stipple tier, ' 0%' label
    MineralNPct = 0 ->  'ga0%' on the Linework label

Zeros arrive from the QField spinbox (Min = 0, so a literal 0 is typeable)
and from any attribute round-trip that loses a NULL - the QML/JS bridge
hands a typed-null REAL to JavaScript as the number 0, which is what made
the sidecar's Reverse and Copy tools stamp 0 widths.  Guarding the render
side means such a 0 is harmless wherever it came from.

The guard is uniformly `coalesce("Field", 0)` so NULL and 0 take the same
branch, mirroring the existing degenerate-value guard in
inject_label_size_scaling.EXTENT_F (`coalesce(@map_scale, 0) <= 0 THEN 1`).

WHY A PATCHER AND NOT A RE-BAKE
Five injectors own these expressions and their constants have been updated
to match, but three of them cannot simply be re-run against the current
template:

  * inject_linework_vein_fields.py  - its label branch matches neither
    `current == "Label"` nor `LABEL_EXPR in current` any more (later
    injectors rewrote the expression), so it bails.
  * inject_overlay_mineralisation.py - its renderer pass short-circuits on
    "categories already present", so the ramp would not be updated.
  * inject_linework_mineral_pcts.py - re-runnable, but there is no reason
    to run three scripts when one targeted patch does all of it.

So this script rewrites the BAKED expressions in place, the same targeted
substring approach inject_linework_detail_scope.py uses.  Once the source
constants and the template agree it is a permanent no-op.

Idempotent and re-runnable; every edit group must hit its exact expected
count, and the QML is validated with ElementTree BEFORE anything is written.

Usage:  python scripts/inject_zero_value_guards.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import sqlite3
import sys
import xml.etree.ElementTree as ET

# Expressions live in styleQML XML-escaped, so the patterns are too.
Q = "&quot;"


def gate(field):
    """`AND "F" IS NOT NULL THEN` -> `AND coalesce("F", 0) > 0 THEN`."""
    return ("AND {q}{f}{q} IS NOT NULL THEN".format(q=Q, f=field),
            "AND coalesce({q}{f}{q}, 0) &gt; 0 THEN".format(q=Q, f=field))


# layer -> [(label, old, new, expected count)]
# Counts are asserted, never assumed: a mismatch aborts before any write.
EDITS = {
    "3 - Linework": [
        # 239 symbol outlineWidth/size dd props + 1 label Size dd prop.
        ("Width_cm ramp gate (stroke + label size)",
         gate("Width_cm")[0], gate("Width_cm")[1], 240),
        # Label text: '' for unrecorded, so 0 stops rendering as '0mm'.
        ("Width_cm label text",
         "CASE WHEN {q}Width_cm{q} IS NULL THEN".format(q=Q),
         "CASE WHEN coalesce({q}Width_cm{q}, 0) &lt;= 0 THEN".format(q=Q),
         1),
        # Per-mineral percentages: 'ga0%' -> 'ga'.
        ("Mineral1Pct label gate", gate("Mineral1Pct")[0],
         gate("Mineral1Pct")[1], 1),
        ("Mineral2Pct label gate", gate("Mineral2Pct")[0],
         gate("Mineral2Pct")[1], 1),
        ("Mineral3Pct label gate", gate("Mineral3Pct")[0],
         gate("Mineral3Pct")[1], 1),
    ],
    "2 - Overlay": [
        # Mineralisation stipple/hatch density ramp: 0 -> middle step.
        ("Percent density ramp",
         "CASE WHEN {q}Percent{q} IS NULL THEN 1".format(q=Q),
         "CASE WHEN coalesce({q}Percent{q}, 0) &lt;= 0 THEN 1".format(q=Q),
         8),
        # Mineralisation label: drop the ' 0%' suffix.
        ("Percent label branch",
         "CASE WHEN {q}Percent{q} IS NOT NULL THEN".format(q=Q),
         "CASE WHEN coalesce({q}Percent{q}, 0) &gt; 0 THEN".format(q=Q),
         1),
    ],
}


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def apply_edits(qml, edits, layer):
    """-> (new_qml, changed_count).  Aborts on any unexpected count."""
    changed = 0
    for label, old, new, expected in edits:
        have_old = qml.count(old)
        have_new = qml.count(new)
        if have_old == 0 and have_new >= expected:
            print(f"  {label}: already guarded ({have_new})")
            continue
        if have_old != expected:
            bail(f"{layer} / {label}: expected {expected} occurrence(s) of the "
                 f"unguarded form, found {have_old} (guarded: {have_new}). "
                 "Template is not in the shape this patch was written for - "
                 "nothing written.")
        qml = qml.replace(old, new)
        changed += have_old
        print(f"  {label}: {have_old} guarded")
    return qml, changed


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")

    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    pending = []
    for layer, edits in EDITS.items():
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        row = cur.fetchone()
        if not row or not row[0]:
            bail(f"no styleQML for {layer!r}")
        print(f"{layer}:")
        qml, changed = apply_edits(row[0], edits, layer)
        if changed == 0:
            continue
        try:
            ET.fromstring(qml)
        except ET.ParseError as exc:
            bail(f"{layer}: edited QML no longer parses, aborting without "
                 f"write: {exc}")
        pending.append((layer, qml, changed))

    if not pending:
        print("no change - every expression is already guarded")
        con.close()
        return

    for layer, qml, changed in pending:
        cur.execute("UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                    (qml, layer))
        assert cur.rowcount == 1, layer
        print(f"{layer}: styleQML updated ({changed} expressions)")
    con.commit()

    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])

    # Round-trip: re-read and confirm the guarded form is in, the bare form out.
    for layer, edits in EDITS.items():
        cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                    (layer,))
        qml = cur.fetchone()[0]
        ET.fromstring(qml)
        for label, old, new, expected in edits:
            assert qml.count(old) == 0, (layer, label, "unguarded form remains")
            assert qml.count(new) >= expected, (layer, label, qml.count(new))
        print(f"round-trip ok: {layer}")
    con.close()


if __name__ == "__main__":
    main()
