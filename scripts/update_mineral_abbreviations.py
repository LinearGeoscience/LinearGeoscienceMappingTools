"""Replace MineralCodes.Value with standard mineral abbreviations.

MineralCodes stored full names in both Value (the code column the
ValueRelation widgets store) and Description. This script rewrites Value
to the standard mineral symbol so features store short codes (Ol, Px,
Qz...), widgets keep displaying the full Description, and the legend
explains code -> meaning.

Symbols follow Whitney & Evans (2010) "Abbreviations for names of
rock-forming minerals", Am. Mineralogist 95:185-187, and the IMA-CNMNC
approved symbol list (Warr 2021, Mineralogical Magazine 85:291-320)
where the species is covered. Informal field terms (Calcareous, Iron
Oxide, Massive Sulphide...), varieties (Amethyst, Fuchsite...) and a few
rare species get LGS-derived codes in the same style. Native elements
use their chemical symbols (Au, Ag, Cu, S, Sb, Bi, As, Pt, Pd) per Warr.

Guards: every Description must be mapped (bails listing any missing or
unknown), abbreviations must be unique case-insensitively, Description
is never modified. Idempotent.

Usage:  python scripts/update_mineral_abbreviations.py [path\\to\\gpkg]
        (defaults to Template/LGS_MappingTemplate.gpkg next to this repo)
"""
import os
import sqlite3
import sys

ABBREVIATIONS = {
    "Actinolite": "Act", "Adularia": "Adl", "Agate": "Agt", "Albite": "Ab",
    "Alkali Feldspar": "Afs", "Allanite": "Aln", "Allophane": "Alp",
    "Almandine": "Alm", "Alunite": "Alu", "Amblygonite": "Aby",
    "Amethyst": "Amy", "Amphibole": "Amp", "Anatase": "Ant",
    "Andalusite": "And", "Andesine": "Ads", "Anhydrite": "Anh",
    "Ankerite": "Ank", "Anorthite": "An", "Anthophyllite": "Ath",
    "Antigorite": "Atg", "Antimony": "Sb", "Apatite": "Ap",
    "Aragonite": "Arg", "Arsenic (Native)": "As", "Arsenopyrite": "Apy",
    "Augite": "Aug", "Awaruite": "Awr", "Azurite": "Azu",
    "Barite": "Brt", "Bastnaesite": "Bsn", "Beryl": "Brl", "Biotite": "Bt",
    "Bismuth": "Bi", "Bismuthinite": "Bin", "Bornite": "Bn",
    "Braunite": "Brn", "Brucite": "Brc", "Bytownite": "Byt",
    "Calaverite": "Clv", "Calcareous": "Ccs", "Calcite": "Cal",
    "Carbon": "C", "Carbonate": "Cb", "Carnotite": "Cnt",
    "Cassiterite": "Cst", "Celestite": "Clt", "Cerussite": "Cer",
    "Chalcedony": "Ccd", "Chalcocite": "Cct", "Chalcopyrite": "Ccp",
    "Chlorite": "Chl", "Chloritoid": "Cld", "Chromite": "Chr",
    "Chrysocolla": "Ccl", "Chrysoprase": "Cpz", "Chrysotile": "Ctl",
    "Cinnabar": "Cin", "Clay": "Cly", "Clinopyroxene": "Cpx",
    "Clinozoisite": "Czo", "Cobaltite": "Cbt", "Cookeite": "Cok",
    "Coloradoite": "Clr", "Columbite": "Clb", "Copper": "Cu",
    "Cordierite": "Crd", "Coronadite": "Cor", "Corundum": "Crn",
    "Covellite": "Cv", "Cubanite": "Cbn", "Cummingtonite": "Cum",
    "Cuprite": "Cpr",
    "Diamond": "Dia", "Dickite": "Dck", "Digenite": "Dg", "Diopside": "Di",
    "Dolomite": "Dol",
    "Elbaite": "Elb", "Electrum": "El", "Enargite": "Eng",
    "Enstatite": "En", "Epidote": "Ep", "Erythrite": "Ery",
    "Eucryptite": "Euc",
    "Feldspar": "Fsp", "Fergusonite": "Fgs", "Ferrocolumbite": "Fcb",
    "Ferroplatinum": "Fpt", "Ferrotantalite": "Ftl", "Fettelite": "Fet",
    "Fluorite": "Fl", "Forsterite": "Fo", "Freibergite": "Frb",
    "Fuchsite": "Fch",
    "Gahnite": "Ghn", "Galena": "Gn", "Garnet": "Grt",
    "Garnierite": "Gnr", "Geikielite": "Gk", "Genthelvite": "Gtv",
    "Geocronite": "Gcr", "Gersdorffite": "Gdf", "Gibbsite": "Gbs",
    "Glaucodot": "Gdt", "Glauconite": "Glt", "Goethite": "Gth",
    "Gold": "Au", "Graphite": "Gr", "Greenockite": "Gck",
    "Grossularite": "Grs", "Grunerite": "Gru", "Gypsum": "Gp",
    "Halite": "Hl", "Heazlewoodite": "Hzl", "Hedenbergite": "Hd",
    "Hematite": "Hem", "Hessite": "Hes", "Hollandite": "Hol",
    "Holmquistite": "Hlm", "Hornblende": "Hbl",
    "Iddingsite": "Idd", "Illite": "Ilt", "Ilmenite": "Ilm",
    "Ilvaite": "Ilv", "Inesite": "Ine", "Iowaite": "Iow",
    "Iron Oxide": "FeOx",
    "Jamesonite": "Jms", "Jarosite": "Jrs", "Jasper": "Jsp",
    "Jordanite": "Jrd",
    "K-Feldspar": "Kfs", "Kaolin": "Kao", "Kaolinite": "Kln",
    "Kermesite": "Krm", "Kesterite": "Kst", "Kinoite": "Kin",
    "Kolbeckite": "Klb", "Kyanite": "Ky",
    "Labradorite": "Lab", "Lepidolite": "Lpd", "Leucite": "Lct",
    "Leucoxene": "Lcx", "Limonite": "Lm", "Linnaeite": "Lin",
    "Lizardite": "Lz", "Loellingite": "Lo", "Luzonite": "Luz",
    "Maghemite": "Mgh", "Magnesite": "Mgs", "Magnetite": "Mag",
    "Malachite": "Mlc", "Manganese": "Mn", "Manganite": "Mnn",
    "Marcasite": "Mrc", "Martite": "Mrt", "Massive Sulphide": "MSul",
    "Metamorphic Olivine": "MtOl", "Metanovacekite": "Mnv", "Mica": "Mca",
    "Microcline": "Mc", "Millerite": "Mlr", "Mimetite": "Mim",
    "Mohite": "Moh", "Molybdenite": "Mol", "Monazite": "Mnz",
    "Montebrasite": "Mtb", "Montmorillonite": "Mnt", "Mooreite": "Moo",
    "Morganite": "Mgn", "Muscovite": "Ms",
    "Nahcolite": "Nah", "Naumannite": "Nmn", "Nepheline": "Nph",
    "Nickeline": "Ncl", "Nontronite": "Non",
    "Oligoclase": "Olg", "Olivine": "Ol", "Opaline silica": "Opl",
    "Orpiment": "Orp", "Orthoclase": "Or", "Orthopyroxene": "Opx",
    "Osmiridium": "OsIr", "Oxidised Sulphide": "OxS",
    "Palladium": "Pd", "Paragonite": "Pg", "Parisite": "Prs",
    "Pentlandite": "Pn", "Petalite": "Ptl", "Petzite": "Ptz",
    "Pezzottaite": "Pzt", "Phlogopite": "Phl", "Phosphate": "Pho",
    "Plagioclase": "Pl", "Platinum": "Pt", "Prehnite": "Prh",
    "Proustite": "Prt", "Pyrite": "Py", "Pyroaurite": "Pya",
    "Pyrochlore": "Pcl", "Pyrolusite": "Pyl", "Pyrophyllite": "Prl",
    "Pyroxene": "Px", "Pyrrhotite": "Po",
    "Quartz": "Qz",
    "Rammelsbergite": "Rmb", "Realgar": "Rlg", "Rhodochrosite": "Rds",
    "Roeblingite": "Rbl", "Roscoelite": "Rsc", "Rutile": "Rt",
    "Samarskite": "Smk", "Sanidine": "Sa", "Saussurite": "Sau",
    "Scapolite": "Scp", "Scheelite": "Sch", "Scorodite": "Scd",
    "Semseyite": "Sms", "Sericite": "Ser", "Serpentine": "Srp",
    "Siderite": "Sd", "Silica": "Slc", "Sillimanite": "Sil",
    "Silver": "Ag", "Skutterudite": "Skt", "Smectite": "Sme",
    "Smithsonite": "Smi", "Sperrylite": "Spy", "Sphalerite": "Sp",
    "Sphene": "Spn", "Spodumene": "Spd", "Stannite": "Stn",
    "Staurolite": "St", "Stephanite": "Ste", "Stibnite": "Sbn",
    "Stichtite": "Stc", "Stilpnomelane": "Stp", "Strontianite": "Str",
    "Sulphide": "Sul", "Sulphur": "S", "Sylvanite": "Svn",
    "Sylvite": "Syl",
    "Talc": "Tlc", "Tantalite": "Tan", "Telluride": "Tel",
    "Tellurite": "Tlr", "Tennantite": "Tnt", "Tenorite": "Tnr",
    "Tetrahedrite": "Ttr", "Thorianite": "Thn", "Thorite": "Thr",
    "Tincalconite": "Tcn", "Tochilinite": "Tch", "Topaz": "Tpz",
    "Torbernite": "Tbn", "Tourmaline": "Tur", "Tremolite": "Tr",
    "Trona": "Trn", "Tschermakite": "Ts",
    "Uraninite": "Urn", "Uvarovite": "Uv",
    "Vanadinite": "Van", "Vermiculite": "Vrm", "Veszelyite": "Vsz",
    "Villiaumite": "Vil", "Violarite": "Vio",
    "Witherite": "Wth", "Wolframite": "Wlf", "Wollastonite": "Wo",
    "Woodallite": "Wdl", "Wurtzite": "Wur",
    "Zaratite": "Zrt", "Zeolite": "Zeo", "Zincite": "Znc",
    "Zinnwaldite": "Znw", "Zircon": "Zrn", "Zoisite": "Zo",
}


def bail(msg):
    print("ERROR:", msg)
    sys.exit(1)


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Template", "LGS_MappingTemplate.gpkg")
    gpkg = sys.argv[1] if len(sys.argv) > 1 else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")

    # Self-check: abbreviations unique (case-insensitive) and well-formed.
    seen = {}
    for name, ab in ABBREVIATIONS.items():
        if not ab or len(ab) > 5:
            bail(f"bad abbreviation for {name!r}: {ab!r}")
        key = ab.lower()
        if key in seen:
            bail(f"duplicate abbreviation {ab!r}: {name!r} and {seen[key]!r}")
        seen[key] = name

    con = sqlite3.connect(gpkg)
    cur = con.cursor()
    rows = cur.execute("SELECT fid, Value, Description FROM MineralCodes").fetchall()

    table_names = {r[2] for r in rows}
    missing = sorted(table_names - set(ABBREVIATIONS))
    extra = sorted(set(ABBREVIATIONS) - table_names)
    if missing:
        bail(f"unmapped Descriptions in MineralCodes: {missing}")
    if extra:
        bail(f"mapping entries not present in MineralCodes: {extra}")
    if len(rows) != len(table_names):
        bail("duplicate Descriptions in MineralCodes - mapping would be ambiguous")

    changed = 0
    for fid, value, desc in rows:
        target = ABBREVIATIONS[desc]
        if value != target:
            cur.execute("UPDATE MineralCodes SET Value=? WHERE fid=?", (target, fid))
            changed += 1
    con.commit()
    print(f"updated {changed} rows" if changed else "already applied (no change)")

    # Validate.
    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    final = cur.execute("SELECT Value, Description FROM MineralCodes").fetchall()
    values = [v for v, _ in final]
    assert len(values) == len({v.lower() for v in values}), "duplicate Values"
    assert all(v == ABBREVIATIONS[d] for v, d in final), "round-trip mismatch"
    print(f"round-trip ok: {len(final)} unique abbreviations "
          f"(e.g. Olivine={ABBREVIATIONS['Olivine']}, "
          f"Pyroxene={ABBREVIATIONS['Pyroxene']}, "
          f"Quartz={ABBREVIATIONS['Quartz']})")
    con.close()


if __name__ == "__main__":
    main()
