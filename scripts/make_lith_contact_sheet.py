"""Render a review sheet for every lithology code's texture.

Draws all 283 codes through the REAL rule-based renderer out of
LGS_MappingTemplate_Patterns.gpkg, so each swatch is the texture in its
tinted colour over that lithology's actual class fill - not an approximation.
Emits a self-contained HTML page (swatches inlined as base64 PNGs) for
publishing as an artifact.

The point is reviewability: 283 assignments are only trustworthy if someone
can look at them. Reads the same Template/patterns/lith_textures.tsv the
injector consumes, so the sheet cannot drift from what the template does.

Run:  "C:\\OSGeo4W\\bin\\python-qgis-ltr.bat" scripts/make_lith_contact_sheet.py [out.html]
"""
import base64
import html
import os
import sqlite3
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import inject_basemap_lith_patterns as inj  # noqa: E402

PX = 132            # swatch width in px
PXH = 88            # swatch height in px
# Map units per swatch. Chosen so the render lands near 1:2500 - inside the
# 1:500-1:4000 band where every texture holds a steady 7-10% ink. At 100 units
# this rendered at 1:9664, past the pattern rule's 1:6000 cutoff, and every
# swatch came out as flat colour with no texture at all.
CELL_H = 26         # map units tall
# The map cell MUST carry the same aspect ratio as the pixel cell. QGIS
# expands the extent to fit the output aspect, so a square map cell drawn
# into a 3:2 pixel cell silently shifts every crop and loses the cells at
# each end of the strip.
CELL_W = CELL_H * PX / PXH
CHUNK = 24          # codes rendered per pass

FAMILY_NAMES = {
    "A": "Alkaline", "F": "Felsic", "H": "Metamorphic", "I": "Intermediate",
    "M": "Mafic", "S": "Sedimentary", "U": "Ultramafic", "V": "Veins",
    "Z": "Sheared / schistose", "R": "Regolith", "T": "Transported cover",
}


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        REPO, "lith_contact_sheet.html")

    con = sqlite3.connect("file:%s?mode=ro" % inj.ORIGINAL.replace("\\", "/"),
                          uri=True)
    rows = con.execute(
        "SELECT Type, Code, Description FROM BasemapCodes").fetchall()
    con.close()
    codes = [c for _t, c, _d in rows]
    tiles = inj.load_tiles()
    tex_map = inj.load_texture_map(codes, tiles)

    from qgis.core import (QgsApplication, QgsVectorLayer, QgsFeature,
                           QgsGeometry, QgsMapSettings, QgsRectangle,
                           QgsCoordinateReferenceSystem,
                           QgsMapRendererCustomPainterJob)
    from qgis.PyQt.QtCore import QSize, QBuffer, QByteArray, QIODevice
    from qgis.PyQt.QtGui import QImage, QPainter, QColor

    QgsApplication.setPrefixPath(os.environ.get(
        "QGIS_PREFIX_PATH", "C:/OSGeo4W/apps/qgis-ltr"), True)
    app = QgsApplication([], False)
    app.initQgis()
    swatch = {}
    try:
        src = QgsVectorLayer("%s|layername=%s" % (inj.TARGET, inj.LAYER),
                             inj.LAYER, "ogr")
        if not src.isValid():
            raise SystemExit("cannot open " + inj.TARGET)
        renderer = src.renderer()

        ordered = sorted(codes)
        for start in range(0, len(ordered), CHUNK):
            batch = ordered[start:start + CHUNK]
            mem = QgsVectorLayer(
                "Polygon?crs=EPSG:3857&field=Lithology1:string"
                "&field=ContactType:string", "t", "memory")
            feats = []
            for i, code in enumerate(batch):
                f = QgsFeature(mem.fields())
                f.setAttribute("Lithology1", code)
                f.setAttribute("ContactType", "None")   # no border in a swatch
                x = i * CELL_W
                f.setGeometry(QgsGeometry.fromWkt(
                    "POLYGON((%f 0,%f 0,%f %f,%f %f,%f 0))"
                    % (x, x + CELL_W, x + CELL_W, CELL_H, x, CELL_H, x)))
                feats.append(f)
            mem.dataProvider().addFeatures(feats)
            mem.updateExtents()
            mem.setRenderer(renderer.clone())

            W = len(batch) * PX
            ms = QgsMapSettings()
            ms.setLayers([mem])
            ms.setExtent(QgsRectangle(0, 0, len(batch) * CELL_W, CELL_H))
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

            for i, code in enumerate(batch):
                cell = im.copy(i * PX, 0, PX, PXH)
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.WriteOnly)
                cell.save(buf, "PNG")
                buf.close()
                swatch[code] = base64.b64encode(bytes(ba)).decode("ascii")
            del mem
        scale = ms.scale()
        del src
    finally:
        app.exitQgis()
        del app

    # ---------------------------------------------------------------- page
    by_family = {}
    for typ, code, desc in rows:
        fam = code[0].upper()
        key = (typ, fam)
        by_family.setdefault(key, []).append((code, desc))
    for v in by_family.values():
        v.sort()

    tex_count = {}
    for t, _n, _i, _v in tex_map.values():
        tex_count[t] = tex_count.get(t, 0) + 1

    parts = [HEAD]
    parts.append(
        '<header class="sheet-head">'
        '<p class="eyebrow">LGS mapping template &middot; 4 - Basemap</p>'
        '<h1>Lithology Texture Review</h1>'
        '<p class="lede">Every one of the %d lithology codes, drawn through the '
        'real renderer: its texture, in its tinted colour, over its own class '
        'fill. %d textures in use. Rendered at 1:%d.</p>'
        '<p class="note-key"><span class="flag"></span> marks an assignment '
        'that needed a judgement call &mdash; those are the ones worth '
        'arguing with.</p>'
        '</header>' % (len(rows), len(tex_count), round(scale)))

    order = sorted(by_family, key=lambda k: (k[0] != "Lithology", k[0], k[1]))
    parts.append('<main>')
    for typ, fam in order:
        items = by_family[(typ, fam)]
        label = FAMILY_NAMES.get(fam, fam)
        parts.append(
            '<section><h2><span class="fam">%s</span>'
            '<span class="fam-meta">%s&thinsp;* &middot; %d codes</span></h2>'
            '<div class="grid">' % (html.escape(label), html.escape(fam),
                                    len(items)))
        for code, desc in items:
            texture, note, ink_name, _variety = tex_map[code]
            rock = desc.split(" - ", 1)[1] if " - " in desc else desc
            flagged = note and note != "-"
            parts.append(
                '<figure class="card%s">'
                '<img alt="%s texture" src="data:image/png;base64,%s" />'
                '<figcaption>'
                '<span class="code">%s</span>'
                '<span class="rock">%s</span>'
                '<span class="tex">%s</span>'
                '%s'
                '</figcaption></figure>'
                % (" flagged" if flagged else "",
                   html.escape(texture), swatch[code],
                   html.escape(code), html.escape(rock),
                   html.escape(texture),
                   ('<span class="note">%s</span>' % html.escape(note))
                   if flagged else ""))
        parts.append('</div></section>')
    parts.append('</main>')

    parts.append('<section class="tally"><h2><span class="fam">Texture use'
                 '</span><span class="fam-meta">%d tiles</span></h2>'
                 '<div class="tally-grid">' % len(tex_count))
    for t in sorted(tex_count, key=lambda k: (-tex_count[k], k)):
        parts.append('<div class="trow"><span class="tex">%s</span>'
                     '<span class="bar"><i style="width:%.1f%%"></i></span>'
                     '<span class="n">%d</span></div>'
                     % (html.escape(t), 100.0 * tex_count[t] / max(tex_count.values()),
                        tex_count[t]))
    parts.append('</div></section>')
    parts.append('</body>')

    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(parts))
    print("wrote %s (%.1f MB, %d swatches)"
          % (out_path, os.path.getsize(out_path) / 1e6, len(swatch)))


HEAD = """<title>Lithology Texture Review</title>
<style>
:root{
  --paper:#faf9f7; --surface:#ffffff; --ink:#151719; --muted:#6b7480;
  --line:#e2ded8; --line-strong:#c9c4bc; --flag:#8a5a2b; --flag-soft:#f2e8dc;
  --shadow:0 1px 2px rgba(21,23,25,.06);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#141518; --surface:#1c1e21; --ink:#e9e7e3; --muted:#949aa3;
    --line:#2b2e33; --line-strong:#3a3e44; --flag:#d09a5e; --flag-soft:#2a2119;
    --shadow:0 1px 2px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"]{
  --paper:#141518; --surface:#1c1e21; --ink:#e9e7e3; --muted:#949aa3;
  --line:#2b2e33; --line-strong:#3a3e44; --flag:#d09a5e; --flag-soft:#2a2119;
  --shadow:0 1px 2px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
body{
  background:var(--paper); color:var(--ink);
  font-family:ui-sans-serif,system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  line-height:1.5; margin:0; padding:clamp(1.5rem,4vw,3.5rem);
  -webkit-font-smoothing:antialiased;
}
.sheet-head{max-width:62ch; margin:0 0 3rem}
.eyebrow{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.72rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--muted); margin:0 0 .75rem;
}
h1{
  font-size:clamp(1.9rem,4.5vw,2.9rem); line-height:1.08; margin:0 0 1rem;
  letter-spacing:-.022em; font-weight:620; text-wrap:balance;
}
.lede{margin:0 0 .9rem; color:var(--muted); font-size:1.03rem}
.note-key{margin:0; font-size:.85rem; color:var(--muted);
  display:flex; align-items:center; gap:.5rem}
.flag{display:inline-block; width:.55rem; height:.55rem; border-radius:50%;
  background:var(--flag); flex:0 0 auto}
main{display:flex; flex-direction:column; gap:2.75rem}
section h2{
  display:flex; align-items:baseline; justify-content:space-between; gap:1rem;
  margin:0 0 1rem; padding-bottom:.5rem;
  border-bottom:1px solid var(--line-strong); font-size:1rem; font-weight:600;
  letter-spacing:-.008em;
}
.fam-meta{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.75rem; color:var(--muted); letter-spacing:.04em;
  font-variant-numeric:tabular-nums; font-weight:400; white-space:nowrap;
}
.grid{
  display:grid; gap:.85rem;
  grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
}
.card{
  margin:0; background:var(--surface); border:1px solid var(--line);
  border-radius:3px; overflow:hidden; box-shadow:var(--shadow);
  display:flex; flex-direction:column;
}
.card.flagged{border-color:var(--flag)}
.card img{display:block; width:100%; height:auto; border-bottom:1px solid var(--line)}
figcaption{padding:.5rem .6rem .6rem; display:flex; flex-direction:column; gap:.1rem}
.code{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.82rem; font-weight:600; letter-spacing:.02em;
}
.rock{font-size:.78rem; line-height:1.3; color:var(--ink)}
.tex{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.68rem; color:var(--muted); letter-spacing:.02em;
}
.note{
  font-size:.7rem; line-height:1.35; color:var(--flag);
  background:var(--flag-soft); border-radius:2px;
  padding:.25rem .35rem; margin-top:.3rem;
}
.tally{margin-top:3rem}
.tally-grid{display:grid; gap:.3rem}
.trow{display:grid; grid-template-columns:11rem 1fr 2.5rem; gap:.7rem;
  align-items:center; font-size:.78rem}
.bar{background:var(--line); height:.5rem; border-radius:1px; overflow:hidden}
.bar i{display:block; height:100%; background:var(--line-strong)}
.trow .n{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-variant-numeric:tabular-nums; text-align:right; color:var(--muted);
}
</style>
<body>
"""

if __name__ == "__main__":
    main()
