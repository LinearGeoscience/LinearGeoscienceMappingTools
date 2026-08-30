"""Render a review sheet for the per-feature Basemap modulation.

The one-colour-per-code tooling (lith_fills.tsv, the legend, the contact
sheet) cannot show what inject_basemap_lith_modulation.py adds, because the
modulation is per FEATURE: the same code renders differently with a second
lithology, a grain-size texture, or a diagnostic mineral. This sheet is the
review path for that: a grid of representative codes x modifier scenarios,
every swatch drawn through the REAL patterns-template renderer.

The memory layers used for rendering do not inherit the template layer's
virtual fields (LGS_Lith2Fill / LGS_TextureNudge), so the sheet re-adds them
with layer.addExpressionField() using the template's OWN expressions - if it
did not, the dd fillColor would error out silently and every swatch would
show the base colour, which is exactly the failure this sheet exists to
catch.

Run:  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" scripts/make_lith_modulation_sheet.py [out.html]
"""
import base64
import html
import os
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import inject_basemap_lith_patterns as inj  # noqa: E402

PX = 116            # swatch width in px
PXH = 84            # swatch height in px
CELL_H = 26         # map units tall - same 1:2500-ish band as the contact
CELL_W = CELL_H * PX / PXH   # sheet, where every texture holds its ink

# Representative rows: one per family plus the codes the feature was asked
# for. Validated against BasemapCodes; a missing code is dropped with a note.
ROW_CODES = ["SST", "SSL", "SGW", "MB", "MG", "MDQ", "FGR", "FD", "IA",
             "UKO", "HGG", "ZS", "VQC", "RCC", "TCOS", "TALL"]

# (column label, {field: value}) - applied on top of Lithology1.
SCENARIOS = [
    ("base", {}),
    ("Lith2 sibling", {"Lithology2": "SIBLING"}),      # resolved per row
    ("Lith2 far", {"Lithology2": "FAR"}),              # resolved per row
    ("v. fine gr.", {"Lith1Texture1": "Very Fine Grained"}),
    ("fine gr.", {"Lith1Texture1": "Fine Grained"}),
    ("coarse gr.", {"Lith1Texture1": "Coarse Grained"}),
    ("v. coarse gr.", {"Lith1Texture1": "Very Coarse Grained"}),
    ("brecciated", {"Lith1Texture1": "Brecciated"}),
    ("foliated", {"Lith1Texture1": "Foliated"}),
    ("+ Qz", {"Lith1Mineral1": "Qz"}),
    ("+ Hem", {"Lith1Mineral1": "Hem"}),
    ("+ Cal", {"Lith1Mineral1": "Cal"}),
    ("worst stack", {"Lithology2": "FAR",
                     "Lith1Texture1": "Pegmatitic",
                     "Lith1Texture2": "Brecciated",
                     "Lith1Mineral1": "Qz"}),
]

FIELDS = ["Lithology1", "Lithology2", "ContactType",
          "Lith1Texture1", "Lith1Texture2", "Lith1Mineral1"]


def resolve_lith2(code, codes):
    """(sibling, far) Lith2 picks for one row code."""
    fam = code[0].upper()
    sib = next((c for c in sorted(codes)
                if c != code and c[0].upper() == fam), None)
    far_fam = "U" if fam != "U" else "F"
    far = next((c for c in sorted(codes) if c[0].upper() == far_fam), None)
    return sib, far


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        REPO, "lith_modulation_sheet.html")

    con = sqlite3.connect("file:%s?mode=ro" % inj.ORIGINAL.replace("\\", "/"),
                          uri=True)
    rows = con.execute(
        "SELECT Code, Description FROM BasemapCodes").fetchall()
    con.close()
    codes = {c for c, _d in rows}
    desc_of = {c: d for c, d in rows}
    row_codes = [c for c in ROW_CODES if c in codes]
    dropped = [c for c in ROW_CODES if c not in codes]
    if dropped:
        print("note: dropped rows not in BasemapCodes: %s"
              % ", ".join(dropped))

    from qgis.core import (QgsApplication, QgsVectorLayer, QgsFeature,
                           QgsGeometry, QgsMapSettings, QgsRectangle,
                           QgsCoordinateReferenceSystem, QgsFields,
                           QgsMapRendererCustomPainterJob)
    from qgis.PyQt.QtCore import QSize, QBuffer, QByteArray, QIODevice
    from qgis.PyQt.QtGui import QImage, QPainter, QColor

    QgsApplication.setPrefixPath(os.environ.get(
        "QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    strips = {}
    try:
        src = QgsVectorLayer("%s|layername=%s" % (inj.TARGET, inj.LAYER),
                             inj.LAYER, "ogr")
        if not src.isValid():
            raise SystemExit("cannot open " + inj.TARGET)
        renderer = src.renderer()

        # the template's virtual fields, verbatim - the modulation dd
        # expressions reference them and must find them on the memory layer
        virtual = []
        fields = src.fields()
        for i in range(fields.count()):
            if fields.fieldOrigin(i) == QgsFields.OriginExpression:
                virtual.append((fields.at(i), src.expressionField(i)))
        names = [f.name() for f, _e in virtual]
        for need in ("LGS_Lith2Fill", "LGS_TextureNudge"):
            if need not in names:
                raise SystemExit("template lacks virtual field %s - run "
                                 "inject_basemap_lith_modulation.py and "
                                 "re-bake" % need)
        print("virtual fields carried over: %s" % ", ".join(names))

        for code in row_codes:
            sib, far = resolve_lith2(code, codes)
            mem = QgsVectorLayer(
                "Polygon?crs=EPSG:3857&" +
                "&".join("field=%s:string" % f for f in FIELDS),
                "t", "memory")
            feats = []
            for i, (_label, mods) in enumerate(SCENARIOS):
                f = QgsFeature(mem.fields())
                f.setAttribute("Lithology1", code)
                f.setAttribute("ContactType", "None")
                for k, v in mods.items():
                    if v == "SIBLING":
                        v = sib
                    elif v == "FAR":
                        v = far
                    if v:
                        f.setAttribute(k, v)
                x = i * CELL_W
                f.setGeometry(QgsGeometry.fromWkt(
                    "POLYGON((%f 0,%f 0,%f %f,%f %f,%f 0))"
                    % (x, x + CELL_W, x + CELL_W, CELL_H, x, CELL_H, x)))
                feats.append(f)
            mem.dataProvider().addFeatures(feats)
            mem.updateExtents()
            for fld, expr in virtual:
                mem.addExpressionField(expr, fld)
            mem.setRenderer(renderer.clone())

            W = len(SCENARIOS) * PX
            ms = QgsMapSettings()
            ms.setLayers([mem])
            ms.setExtent(QgsRectangle(0, 0, len(SCENARIOS) * CELL_W, CELL_H))
            ms.setOutputSize(QSize(W, PXH))
            ms.setBackgroundColor(QColor(255, 255, 255))
            ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
            im = QImage(QSize(W, PXH), QImage.Format_ARGB32_Premultiplied)
            im.fill(QColor(255, 255, 255))
            p = QPainter(im)
            job = QgsMapRendererCustomPainterJob(ms, p)
            job.start()
            job.waitForFinished()
            p.end()

            cells = []
            for i in range(len(SCENARIOS)):
                cell = im.copy(i * PX, 0, PX, PXH)
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.WriteOnly)
                cell.save(buf, "PNG")
                buf.close()
                cells.append(base64.b64encode(bytes(ba)).decode("ascii"))
            strips[code] = (cells, sib, far)
            del mem
        scale = ms.scale()
        del src
    finally:
        app.exitQgis()
        del app

    # ---------------------------------------------------------------- page
    parts = [HEAD]
    parts.append(
        '<header class="sheet-head">'
        '<p class="eyebrow">LGS mapping template &middot; 4 - Basemap</p>'
        '<h1>Per-feature Modulation Review</h1>'
        '<p class="lede">The same lithology code under its modifiers: a second '
        'lithology tints the fill toward that unit\'s colour, grain size '
        'scales the texture tile, a diagnostic mineral tints the pattern ink. '
        'Every swatch is the real renderer. Rendered at 1:%d.</p>'
        '</header>' % round(scale))
    parts.append('<main><table><thead><tr><th class="rowhead">code</th>')
    for label, _m in SCENARIOS:
        parts.append('<th>%s</th>' % html.escape(label))
    parts.append('</tr></thead><tbody>')
    for code in [c for c in ROW_CODES if c in strips]:
        cells, sib, far = strips[code]
        desc = desc_of.get(code, "")
        rock = desc.split(" - ", 1)[1] if " - " in desc else desc
        parts.append(
            '<tr><td class="rowhead"><span class="code">%s</span>'
            '<span class="rock">%s</span>'
            '<span class="tex">sib %s &middot; far %s</span></td>'
            % (html.escape(code), html.escape(rock),
               html.escape(sib or "-"), html.escape(far or "-")))
        for png in cells:
            parts.append('<td><img alt="" '
                         'src="data:image/png;base64,%s" /></td>' % png)
        parts.append('</tr>')
    parts.append('</tbody></table></main></body>')

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(parts))
    print("wrote %s (%.1f MB, %d rows x %d scenarios)"
          % (out_path, os.path.getsize(out_path) / 1e6,
             len(strips), len(SCENARIOS)))


HEAD = """<title>Lithology Modulation Review</title>
<style>
:root{
  --paper:#faf9f7; --surface:#ffffff; --ink:#151719; --muted:#6b7480;
  --line:#e2ded8; --line-strong:#c9c4bc;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#141518; --surface:#1c1e21; --ink:#e9e7e3; --muted:#949aa3;
    --line:#2b2e33; --line-strong:#3a3e44;
  }
}
:root[data-theme="dark"]{
  --paper:#141518; --surface:#1c1e21; --ink:#e9e7e3; --muted:#949aa3;
  --line:#2b2e33; --line-strong:#3a3e44;
}
*{box-sizing:border-box}
body{
  background:var(--paper); color:var(--ink);
  font-family:ui-sans-serif,system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  line-height:1.5; margin:0; padding:clamp(1.5rem,4vw,3.5rem);
}
.sheet-head{max-width:62ch; margin:0 0 2.5rem}
.eyebrow{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.72rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--muted); margin:0 0 .75rem;
}
h1{font-size:clamp(1.9rem,4.5vw,2.9rem); line-height:1.08; margin:0 0 1rem;
  letter-spacing:-.022em; font-weight:620}
.lede{margin:0; color:var(--muted); font-size:1.03rem}
main{overflow-x:auto}
table{border-collapse:collapse}
th{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.66rem; font-weight:400; color:var(--muted); padding:.3rem .25rem;
  text-align:left; white-space:nowrap}
td{padding:1px}
td img{display:block; border:1px solid var(--line)}
.rowhead{padding-right:.8rem; vertical-align:top; min-width:9rem}
.code{display:block;
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.82rem; font-weight:600}
.rock{display:block; font-size:.74rem; line-height:1.3}
.tex{display:block;
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.64rem; color:var(--muted)}
</style>
<body>
"""

if __name__ == "__main__":
    main()
