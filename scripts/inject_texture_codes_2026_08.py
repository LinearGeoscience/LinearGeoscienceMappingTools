"""Add the Aug 2026 texture codes to the TextureCodes lookup.

User request: the 328-row list carried Aphanitic/Phaneritic but no plain
grainsize terms, and a review against it turned up a few more standard
textures with no row. Fourteen additions, user-approved 27 Aug 2026:

    Grainsize        Very Fine Grained, Fine Grained, Medium Grained,
                     Coarse Grained, Very Coarse Grained
    Silica           Cryptocrystalline, Chalcedonic (only Microcrystalline
                     and Opaline existed)
    Singles          Drusy (Vuggy/Comb/Cockade existed, Drusy did not),
                     Platy (Flaggy/Fissile/Bladed existed)
    Extras spotted in the same review - cut any at review time:
                     Clayey (completes Sandy/Silty/Muddy/Pebbly/Gravelly),
                     Interstitial (igneous), Nematoblastic (completes the
                     Granoblastic/Lepidoblastic/Poikiloblastic set), Moss
                     (epithermal suite beside Comb/Cockade/Colloform),
                     Patchy (Pervasive/Disseminated precedent)

Plain lookup insert - no styling, no widget changes; every ValueRelation
onto TextureCodes (Lith1Texture1/2, Lith2Texture1/2, VeinTexture) picks
the rows up as soon as they exist. As in every existing row, Code and
Desciption hold the same string - and yes, the column really is spelled
"Desciption"; the legend and the baked widget configs hard-code the typo.

Idempotent and re-runnable: the insert group must be exactly 0 or 14
codes present, anything else aborts without writing. Fids append 335-348
(current max 334; fid gaps 19/101/... are audit deletions, left alone).

Usage:  python scripts/inject_texture_codes_2026_08.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import sqlite3
import sys
import uuid

TABLE = "TextureCodes"
COLUMN = "Desciption"   # sic - load-bearing typo, never rename
FIRST_FID = 335         # current max(fid) = 334

CODES = [
    "Very Fine Grained",
    "Fine Grained",
    "Medium Grained",
    "Coarse Grained",
    "Very Coarse Grained",
    "Cryptocrystalline",
    "Chalcedonic",
    "Drusy",
    "Platy",
    "Clayey",
    "Interstitial",
    "Nematoblastic",
    "Moss",
    "Patchy",
]


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def row_uuid(code):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "lgs-texture:" + code))


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{TABLE}")')]
    if cols != ["fid", "Code", COLUMN, "UUID"]:
        bail(f"{TABLE} shape changed: {cols}")

    before = cur.execute(f'SELECT COUNT(*) FROM "{TABLE}"').fetchone()[0]
    existing = {c for (c,) in cur.execute(
        f'SELECT Code FROM "{TABLE}" WHERE Code IN (%s)'
        % ",".join("?" * len(CODES)), CODES)}
    if existing and len(existing) != len(CODES):
        bail(f"partial code state: {sorted(existing)} already present")

    if existing:
        print(f"already applied ({before} rows, no change)")
    else:
        max_fid = cur.execute(f'SELECT MAX(fid) FROM "{TABLE}"').fetchone()[0]
        if max_fid != FIRST_FID - 1:
            bail(f"max(fid) is {max_fid}, expected {FIRST_FID - 1} - "
                 "table shape changed, re-check FIRST_FID")
        for i, code in enumerate(CODES):
            cur.execute(
                f'INSERT INTO "{TABLE}" (fid, Code, "{COLUMN}", UUID) '
                "VALUES (?,?,?,?)",
                (FIRST_FID + i, code, code, row_uuid(code)))
        con.commit()
        print(f"{TABLE}: {len(CODES)} codes appended (fids "
              f"{FIRST_FID}-{FIRST_FID + len(CODES) - 1})")

    # ---------------- validation --------------------------------------
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    n = cur.execute(f'SELECT COUNT(*) FROM "{TABLE}"').fetchone()[0]
    assert n == before + (0 if existing else len(CODES)), n
    for code in CODES:
        got = cur.execute(
            f'SELECT Code, "{COLUMN}", UUID FROM "{TABLE}" WHERE Code=?',
            (code,)).fetchall()
        assert len(got) == 1, (code, got)
        assert got[0][0] == got[0][1] == code, got
        assert got[0][2] == row_uuid(code), got
    uuids = [r[0] for r in cur.execute(f'SELECT UUID FROM "{TABLE}"')]
    assert len(set(uuids)) == n and all(len(x) == 36 for x in uuids)
    print(f"round-trip ok: {n} texture codes, all {len(CODES)} additions "
          "present exactly once")
    con.close()


if __name__ == "__main__":
    main()
