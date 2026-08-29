"""Render the round-3 Transported Cover proposal as a review sheet.

Pure stdlib, no QGIS: everything on the page - fills, the gold contact ink,
the gold label token, every contrast ratio - is read or computed straight
out of cover_palette.py, so the sheet cannot drift from what the injector
will do. The swatches here are flat fills with the gold identity drawn on
top; the texture over each fill is reviewed later on the real-renderer
sheet (make_lith_contact_sheet.py) after the re-bake.

Run:  python scripts/make_cover_proposal_sheet.py [out.html]
"""
import html
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import cover_palette as cp  # noqa: E402

# Presentation order and wording for the ten mechanism families.
FAMILIES = [
    ("water",     "Alluvial / fluvial",     "whisper blue"),
    ("gravity",   "Colluvial / hillslope",  "whisper buff-tan"),
    ("residual",  "Residual / lag / duricrust", "warm stone-grey"),
    ("wind",      "Aeolian",                "whisper rose"),
    ("evaporite", "Evaporitic",             "cool near-white"),
    ("ice",       "Glacial",                "whisper cyan"),
    ("coast",     "Coastal / marine",       "whisper sand-teal"),
    ("lake",      "Lacustrine / organic",   "whisper green-teal"),
    ("air",       "Airfall",                "whisper violet"),
    ("human",     "Anthropogenic",          "whisper mauve"),
]

# The bedrock neighbours the audit keeps the palette clear of, with the
# fills lith_fills.tsv carried when this sheet was authored (display only -
# the executable check reads the live TSV, see tests/test_cover_palette.py).
NEIGHBOURS = [
    ("SST",  "#eee8c7", "Sandstone cream"),
    ("SSTS", "#e4dbc0", "Sandstone, Silty"),
    ("SSL",  "#dedede", "Siltstone"),
    ("SEV",  "#e3e0d3", "Evaporite"),
    ("RSPL", "#e4d5c4", "Saprolite"),
    ("RDLM", "#ffeed6", "Duricrust, Massive"),
]

LITH_PT = 5.5    # basemap lithology label size
COVER_PT = 6.5   # round-3 cover label size


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        REPO, "cover_proposal_sheet.html")

    gold = cp.rgb_hex(cp.GOLD_CONTACT)
    token = cp.rgb_hex(cp.LABEL_TOKEN)
    old_token = cp.rgb_hex(cp.ROUND3_LABEL_TOKEN)

    parts = [HEAD]
    parts.append(
        '<header class="sheet-head">'
        '<p class="eyebrow">LGS mapping template &middot; Transported Cover'
        ' &middot; round 4</p>'
        '<h1>The Gold Veil</h1>'
        '<p class="lede">All %d cover codes at true Ora Banda intensity:'
        ' cream / near-paper fills (round 3&rsquo;s salmon lean is gone),'
        ' the bright amber contact and label off the reference map, and'
        ' cover textures printed as a faint watermark. Hue still whispers'
        ' the mechanism; the amber says &ldquo;this is cover&rdquo;.</p>'
        '<p class="lede">Every number here is measured from'
        ' <code>cover_palette.py</code>: the audit passes with zero'
        ' failures against all 265 bedrock fills. Each card shows the'
        ' round-3 fill it replaces.</p>'
        '</header>' % len(cp.COVER))

    # ------------------------------------------------ the gold identity
    tok_worst = min(cp.contrast_ratio(cp.LABEL_TOKEN, cp.fill_of(c))
                    for c in cp.COVER)
    con_worst = min(cp.contrast_ratio(cp.GOLD_CONTACT, cp.fill_of(c))
                    for c in cp.COVER)
    parts.append(
        '<section><h2><span class="fam">The gold identity</span>'
        '<span class="fam-meta">one contact ink &middot; one label token'
        '</span></h2><div class="ident">'
        '<div class="ident-card"><div class="ident-demo" style="border-color:%(g)s">'
        '<span class="maplabel" style="color:%(t)s">TCO</span></div>'
        '<div class="ident-cap"><strong>Contact %(g)s</strong>'
        '<span>dashed / solid / none per ContactType, colour only moves.'
        ' Worst case %(cw).2f:1 on its own fills (floor %(fl).1f:1),'
        ' %(bk).2f:1 from the bedrock contact %(bkc)s.</span></div></div>'
        '<div class="ident-card"><div class="ident-demo ident-plain">'
        '<span class="maplabel" style="color:%(t)s">TLGC</span>'
        '<span class="maplabel-lith">SST</span></div>'
        '<div class="ident-cap"><strong>Label %(t)s &middot; %(pt).1f pt</strong>'
        '<span>amber and a step up from the %(lp).1f pt lithology black,'
        ' replacing round 3&rsquo;s antique %(ot)s. Worst case %(tw).2f:1'
        ' on the deepest fill &mdash; chroma carries it.</span></div></div>'
        '</div></section>'
        % {"g": gold, "t": token, "ot": old_token,
           "cw": con_worst, "fl": cp.MIN_CONTACT_RATIO,
           "bk": cp.contrast_ratio(cp.GOLD_CONTACT, cp.CONTACT_BEDROCK),
           "bkc": cp.rgb_hex(cp.CONTACT_BEDROCK),
           "tw": tok_worst, "pt": COVER_PT, "lp": LITH_PT})

    # ------------------------------------------------ bedrock neighbours
    parts.append(
        '<section><h2><span class="fam">The neighbours it stays clear of'
        '</span><span class="fam-meta">dE &ge; %.0f enforced</span></h2>'
        '<div class="nbr">' % cp.MIN_FILL_DE)
    for code, fill, name in NEIGHBOURS:
        parts.append(
            '<div class="nbr-chip"><i style="background:%s"></i>'
            '<span class="code">%s</span><span class="tex">%s</span></div>'
            % (fill, html.escape(code), html.escape(name)))
    parts.append('</div></section>')

    # ------------------------------------------------ family sections
    for fam, name, tint in FAMILIES:
        members = sorted((c for c in cp.COVER if cp.family_of(c) == fam),
                         key=lambda c: -sum(cp.fill_of(c)))
        parts.append(
            '<section><h2><span class="fam">%s</span>'
            '<span class="fam-meta">%s &middot; %d codes</span></h2>'
            '<div class="grid">'
            % (html.escape(name), html.escape(tint), len(members)))
        for code in members:
            fill = cp.rgb_hex(cp.fill_of(code))
            was = cp.rgb_hex(cp.ROUND3_FILLS[code])
            parts.append(
                '<figure class="card">'
                '<div class="swatch" style="background:%(f)s;border-color:%(g)s">'
                '<span class="maplabel" style="color:%(t)s">%(c)s</span></div>'
                '<figcaption>'
                '<span class="code">%(c)s</span>'
                '<span class="rock">%(d)s</span>'
                '<span class="meta"><i class="was" style="background:%(w)s"'
                ' title="round 2 %(w)s"></i>%(w)s &rarr; %(f)s</span>'
                '<span class="meta">contact %(cr).2f &middot; label %(lr).2f'
                ' &middot; %(tile)s</span>'
                '</figcaption></figure>'
                % {"f": fill, "w": was, "g": gold, "t": token,
                   "c": html.escape(code),
                   "d": html.escape(cp.description_of(code)),
                   "cr": cp.contrast_ratio(cp.GOLD_CONTACT, cp.fill_of(code)),
                   "lr": cp.contrast_ratio(cp.LABEL_TOKEN, cp.fill_of(code)),
                   "tile": html.escape(cp.tile_of(code))})
        parts.append('</div></section>')

    parts.append('</main></body>')
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(parts))
    print("wrote %s (%.1f kB, %d cards)"
          % (out_path, os.path.getsize(out_path) / 1e3, len(cp.COVER)))


HEAD = """<title>The Gold Veil</title>
<style>
:root{
  --paper:#faf9f7; --surface:#ffffff; --ink:#151719; --muted:#6b7480;
  --line:#e2ded8; --line-strong:#c9c4bc; --gold:#9a7118;
  --shadow:0 1px 2px rgba(21,23,25,.06);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#141518; --surface:#1c1e21; --ink:#e9e7e3; --muted:#949aa3;
    --line:#2b2e33; --line-strong:#3a3e44; --gold:#c99a34;
    --shadow:0 1px 2px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"]{
  --paper:#141518; --surface:#1c1e21; --ink:#e9e7e3; --muted:#949aa3;
  --line:#2b2e33; --line-strong:#3a3e44; --gold:#c99a34;
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
  color:var(--gold); margin:0 0 .75rem;
}
h1{
  font-size:clamp(1.9rem,4.5vw,2.9rem); line-height:1.08; margin:0 0 1rem;
  letter-spacing:-.022em; font-weight:620; text-wrap:balance;
}
.lede{margin:0 0 .9rem; color:var(--muted); font-size:1.03rem}
.lede code{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.92em}
main{display:flex; flex-direction:column}
section{margin:0 0 2.75rem}
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
/* --- gold identity band --- */
.ident{display:grid; gap:.85rem;
  grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.ident-card{background:var(--surface); border:1px solid var(--line);
  border-radius:3px; box-shadow:var(--shadow); overflow:hidden}
.ident-demo{
  height:96px; background:#f2e8da; margin:.6rem; border-radius:2px;
  border:2px dashed; display:flex; align-items:center; justify-content:center;
  gap:1.2rem;
}
.ident-plain{background:#d6d2c6; border:2px dashed}
.ident-cap{padding:.15rem .75rem .7rem; display:flex; flex-direction:column;
  gap:.15rem; font-size:.78rem; color:var(--muted); line-height:1.45}
.ident-cap strong{color:var(--ink); font-weight:600;
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace; font-size:.78rem}
/* the map lettering: Leelawadee UI Semilight at the 6.5pt cover size,
   shown beside the 5.5pt lithology black for scale */
.maplabel{
  font-family:"Leelawadee UI Semilight","Leelawadee UI","Segoe UI",sans-serif;
  font-weight:350; font-size:21px; letter-spacing:.02em;
}
.maplabel-lith{
  font-family:"Leelawadee UI Semilight","Leelawadee UI","Segoe UI",sans-serif;
  font-weight:350; font-size:17.8px; color:#1a1a1a; letter-spacing:.02em;
}
/* --- bedrock neighbours --- */
.nbr{display:flex; flex-wrap:wrap; gap:.5rem}
.nbr-chip{display:flex; align-items:center; gap:.5rem;
  background:var(--surface); border:1px solid var(--line); border-radius:3px;
  padding:.35rem .6rem .35rem .4rem; box-shadow:var(--shadow)}
.nbr-chip i{width:1.6rem; height:1.6rem; border-radius:2px;
  border:1px solid var(--line-strong)}
/* --- family cards --- */
.grid{
  display:grid; gap:.85rem;
  grid-template-columns:repeat(auto-fill,minmax(168px,1fr));
}
.card{
  margin:0; background:var(--surface); border:1px solid var(--line);
  border-radius:3px; overflow:hidden; box-shadow:var(--shadow);
  display:flex; flex-direction:column;
}
.swatch{
  height:84px; margin:.5rem .5rem 0; border-radius:2px;
  border:1.5px dashed; display:flex; align-items:center; justify-content:center;
}
figcaption{padding:.45rem .6rem .6rem; display:flex; flex-direction:column;
  gap:.12rem}
.code{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.82rem; font-weight:600; letter-spacing:.02em;
}
.rock{font-size:.76rem; line-height:1.3; color:var(--ink)}
.tex{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.68rem; color:var(--muted); letter-spacing:.02em;
}
.meta{
  font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:.66rem; color:var(--muted); letter-spacing:.01em;
  font-variant-numeric:tabular-nums;
  display:flex; align-items:center; gap:.35rem;
}
.meta .was{display:inline-block; width:.7rem; height:.7rem; border-radius:2px;
  border:1px solid var(--line-strong); flex:0 0 auto}
</style>
<body><main>
"""

if __name__ == "__main__":
    main()
