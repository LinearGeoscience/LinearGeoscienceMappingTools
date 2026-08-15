"""Structural symbol repair for 1 - FieldNotebook (+ 3 - Linework regressions).

The 86 FieldNotebook structural SVG markers are Illustrator/Inkscape
exports embedded as base64 with hardcoded colours in CSS <style> blocks
(or inline style attributes), so the QGIS fill / stroke colour / stroke
width controls are inert.  This injector rewrites every embedded SVG to
the parameterized form the Linework decorations already use:

    stroke="param(outline) #131313"  fill="param(fill) #131313"
    stroke-width="param(outline-width) 15"

and makes the whole set consistent (user decisions 2026-08-15):

  * one black: #000/#000000/#2D2D2D all unify to #131313; provably
    invisible cruft (unstyled zero-area duplicate paths, fill:none
    no-stroke helpers) is deleted;
  * one size: every marker becomes 30 Point.  The FAC family (authored
    25 pt) is wrapper-scaled x25/30 about the canvas centre and the FAP
    family (authored 39 pt, glyph spanning only 420 of the 500 canvas)
    is wrapper-scaled x500/420 about its strike-line centre, so the
    uniform size value reproduces the authored footprints;
  * one stroke setting: QML outline_width 1.3 Point everywhere (the
    authored equivalent was 0.9 pt; 1.3 pt is a deliberate weight bump
    so symbols stay legible over mapping data - user 2026-08-15);
  * unique graphics: the 7 duplicate groups (CT/FB/LAY/DYK,
    FO/CLV/SCR/GSN, LNS/L1-L5, STR/SLK/SLF, SZC/MYL/SZBDY, FAP/FAPCR,
    FAC/FACSP) get path-only modifier glyphs; clones shed the parent's
    inherited <text> label (L1 rendered "LNS", SLK "LSTR");
  * generation lineations recoded: L1-L5 (which wrongly cloned the LNS
    stretching-lineation graphic) become LNI1-LNI5 - the LNI arrow plus
    a bold Century Gothic 'L1'..'L5' label baked as path outlines (no
    font needed at render time) - in both renderer and FieldNotebookCodes;
  * FAP1-5 digit <text> sat at x 437-560, overflowing the canvas
    (already clipped); the digits are relocated below the axial plane.

Per-generation accent colours (F1 #1E90FF, F2 #FF00FF, F3 #FFA500,
F4 #32CD32, F5 #FF0000) are preserved by writing them into the QML
color/outline_color options as the param defaults.  The previously
inert QML colour options held junk and are overwritten wholesale.

Deliberate visual changes, everything else must render identically:
black unification, FAX5 shaft #FF1717 -> #FF0000, invisible-cruft
deletion, the variant glyphs, FAP digit relocation, and every stroke
rendering at the common 1.3 pt weight.

Second pass: the 3 Linework SvgMarkers that regressed to hardcoded
#131313 (1 in "Formline - S0 (Younging Known)", 2 in "Costean") go
through the same engine (no variants, no rescale; outline_width set to
the authored-equivalent value).

The FieldNotebook styleSLD is deliberately untouched: it is not
maintained per-code for this layer.  <text> in the retained base
symbols (BAX, FAX*, VN family, ...) is a known QField/Android font
caveat, out of scope here.

Idempotent and re-runnable; QML parse-validated BEFORE writing.

Usage:  python scripts/inject_fieldnotebook_structural_symbols.py [gpkg]
        add --dump DIR to write before/after SVGs + contact_sheet.html
"""
import base64
import hashlib
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET

FN_LAYER = "1 - FieldNotebook"
LW_LAYER = "3 - Linework"
SVG_NS = "http://www.w3.org/2000/svg"
FOREIGN = ("sodipodi", "inkscape")

BLACK = "#131313"
CANON = {"#000000": BLACK, "#2d2d2d": BLACK, "#131313": BLACK,
         "#00ff00": "#32CD32", "#008000": "#32CD32",
         "#fe0000": "#FF0000", "#ff1717": "#FF0000",
         "#1e90ff": "#1E90FF", "#ff00ff": "#FF00FF",
         "#ffa500": "#FFA500", "#32cd32": "#32CD32",
         "#ff0000": "#FF0000"}

GEN_HEX = {"1": "#1E90FF", "2": "#FF00FF", "3": "#FFA500",
           "4": "#32CD32", "5": "#FF0000"}
EXPECT_ACCENT = {}
for _g, _h in GEN_HEX.items():
    EXPECT_ACCENT["FAP" + _g] = _h
    for _s in ("", "M", "S", "Z"):
        EXPECT_ACCENT["FAX" + _g + _s] = _h          # 25 accent codes

SIZE = "30"                       # Point, uniform
OUTLINE_W = "1.3"                 # Point; deliberate bump over the authored
                                  # 0.9 pt so symbols read over mapping data
MAIN_W_LO, MAIN_W_HI = 10.0, 20.0  # stroke widths that count as "main"
SNAP_15_LO, SNAP_15_HI = 13.5, 16.5  # near-15 widths snap to 15

FAC_FAMILY = {"FAC", "FACP", "FACSP"}                    # authored 25 pt
FAP_FAMILY = {"FAP", "FAP1", "FAP2", "FAP3", "FAP4", "FAP5",
              "FAPK", "FAPSZ", "FAPCR"}                  # authored 39 pt
FAC_SCALE = 25.0 / 30.0
FAP_SCALE = 500.0 / 420.0

TEXT_DELETE = {"LNI1", "LNI2", "LNI3", "LNI4", "LNI5", "SLK", "SLF"}
TEXT_RELOCATE = {c: (300.0, 410.0) for c in
                 ("FAP1", "FAP2", "FAP3", "FAP4", "FAP5")}

# Generation lineations were miscoded L1-L5 cloning the LNS graphic; they
# are LNI1-LNI5: the LNI arrow plus a digit (user decision 2026-08-15).
RENAME = {"L%d" % i: "LNI%d" % i for i in (1, 2, 3, 4, 5)}
RENAME_LABEL = {"LNI%d" % i: "LNI%d - L%d Intersection Lineation" % (i, i)
                for i in (1, 2, 3, 4, 5)}
CLONE_SOURCE = {"LNI%d" % i: "LNI" for i in (1, 2, 3, 4, 5)}

# Bold Century Gothic "L1".."L5" outlines (extracted from GOTHICB.TTF via
# matplotlib TextPath, y-down, height 100) so the generation labels need
# no font at render time and match the 1.3 pt line weight.
FONT_LABELS = {
    "L1": ("M11.4,0.0 L30.5,0.0 L30.5,81.9 L58.2,81.9 L58.2,100.0 L11.4,100.0 L11.4,0.0 Z M84.2,0.0 L112.7,0.0 L112.7,100.0 L93.7,100.0 L93.7,17.9 L73.1,17.9 L84.2,0.0 Z", 112.7),
    "L2": ("M11.1,2.5 L29.7,2.5 L29.7,82.3 L56.8,82.3 L56.8,100.0 L11.1,100.0 L11.1,2.5 Z M83.4,33.9 L65.3,33.9 Q66.0,18.1 75.2,9.1 Q84.4,0.0 98.8,0.0 Q107.7,0.0 114.5,3.8 Q121.3,7.5 125.3,14.6 Q129.4,21.6 129.4,28.9 Q129.4,37.6 124.5,47.6 Q119.6,57.6 106.4,71.3 L95.5,82.8 L130.2,82.8 L130.2,100.0 L62.7,100.0 L62.7,91.1 L92.8,60.3 Q103.8,49.3 107.4,42.5 Q111.0,35.8 111.0,30.4 Q111.0,24.7 107.2,21.1 Q103.5,17.4 97.6,17.4 Q91.6,17.4 87.6,21.8 Q83.7,26.3 83.4,33.9 Z", 130.2),
    "L3": ("M10.9,2.4 L29.0,2.4 L29.0,80.3 L55.4,80.3 L55.4,97.6 L10.9,97.6 L10.9,2.4 Z M83.5,25.9 L66.1,25.9 Q67.4,15.3 73.7,8.9 Q82.3,0.0 95.5,0.0 Q107.2,0.0 115.1,7.5 Q123.0,14.9 123.0,25.1 Q123.0,31.5 119.6,36.7 Q116.1,41.9 109.5,45.2 Q118.2,47.8 123.1,54.2 Q127.9,60.7 127.9,69.4 Q127.9,82.2 118.5,91.1 Q109.0,100.0 94.4,100.0 Q80.6,100.0 71.8,91.6 Q63.1,83.2 62.3,68.8 L80.2,68.8 Q81.4,76.2 85.3,79.8 Q89.3,83.4 95.4,83.4 Q101.7,83.4 105.9,79.3 Q110.1,75.2 110.1,69.3 Q110.1,62.8 104.4,58.4 Q98.8,53.9 88.2,53.8 L88.2,38.2 Q94.7,37.7 97.9,36.2 Q101.2,34.7 102.9,32.0 Q104.7,29.4 104.7,26.4 Q104.7,22.5 102.0,20.0 Q99.3,17.4 94.9,17.4 Q91.0,17.4 87.8,19.8 Q84.6,22.1 83.5,25.9 Z", 127.9),
    "L4": ("M11.1,2.5 L29.7,2.5 L29.7,82.3 L56.8,82.3 L56.8,100.0 L11.1,100.0 L11.1,2.5 Z M104.7,0.0 L123.3,0.0 L123.3,62.8 L131.9,62.8 L131.9,80.0 L123.3,80.0 L123.3,100.0 L105.1,100.0 L105.1,80.0 L62.5,80.0 L62.5,62.8 L104.7,0.0 Z M105.1,62.8 L105.1,30.1 L82.8,62.8 L105.1,62.8 Z", 131.9),
    "L5": ("M11.1,0.0 L29.7,0.0 L29.7,79.8 L56.8,79.8 L56.8,97.5 L11.1,97.5 L11.1,0.0 Z M82.4,0.0 L128.1,0.0 L128.1,17.1 L96.3,17.1 L92.3,34.9 Q94.0,34.4 95.6,34.2 Q97.1,33.9 98.6,33.9 Q111.9,33.9 120.6,43.0 Q129.4,52.0 129.4,66.2 Q129.4,80.4 119.7,90.2 Q110.0,100.0 96.1,100.0 Q83.6,100.0 74.7,92.9 Q65.7,85.8 62.9,73.5 L82.4,73.5 Q84.7,78.0 88.3,80.4 Q92.0,82.7 96.5,82.7 Q102.6,82.7 107.0,78.3 Q111.3,73.9 111.3,66.9 Q111.3,60.1 107.2,55.8 Q103.2,51.5 97.5,51.5 Q94.5,51.5 91.5,53.0 Q88.6,54.5 85.7,57.6 L70.6,54.2 L82.4,0.0 Z", 129.4),
}


def _label(n, cx, cy):
    d, w = FONT_LABELS[n]
    return {"tag": "path", "solid": True, "d": d,
            "transform": "translate(%g,%g)" % (cx - w / 2, cy)}


def _stroke(d, sw="15"):
    return {"tag": "path", "d": d, "sw": sw}


# Modifier glyphs, viewport coordinates (before any family rescale).
VARIANTS = {
    "FB":    [_stroke("M190.8,157.7 v104.5"), _stroke("M310.8,157.7 v104.5")],
    "LAY":   [_stroke("M190.8,209.9 v52.3"), _stroke("M310.8,209.9 v52.3")],
    "DYK":   [_stroke("M175,209.9 h150")],
    "CLV":   [_stroke("M251,303.7 v52")],
    "SCR":   [_stroke("M60,303.7 l22,-22 l22,22 l22,-22 l22,22", "12")],
    "GSN":   [_stroke("M100,303.7 v-52"), _stroke("M400,303.7 v-52")],
    "LNI1":  [_label("L1", 340, 330)],
    "LNI2":  [_label("L2", 340, 330)],
    "LNI3":  [_label("L3", 340, 330)],
    "LNI4":  [_label("L4", 340, 330)],
    "LNI5":  [_label("L5", 340, 330)],
    "SLK":   [_stroke("M203,310 h71", "14")],
    "SLF":   [{"tag": "polygon", "solid": True,
               "points": "238.6,282 262,310 238.6,338 215.2,310"}],
    "MYL":   [_stroke("M251,304.5 v52")],
    "SZBDY": [_stroke("M0.5,340 h499.3")],
    "FAPCR": [_stroke("M150,210 l24,-28 l24,28 l24,-28 l24,28 l24,-28", "12")],
    "FACSP": [_stroke("M360,70 v100", "12"), _stroke("M316.7,95 l86.6,50", "12"),
              _stroke("M403.3,95 l-86.6,50", "12")],
}

DRAWABLE = {"path", "line", "rect", "polygon", "polyline",
            "circle", "ellipse", "text", "tspan"}


def bail(msg):
    raise SystemExit("ABORT: " + msg)


def tag_of(el):
    return el.tag.rsplit("}", 1)[-1]


def is_foreign(name):
    return any(f in name for f in FOREIGN)


def parse_css(text):
    """{class: {prop: value}} from a stylesheet of bare class rules."""
    rules = {}
    body = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for sel, decl in re.findall(r"([^{}]+)\{([^}]*)\}", body):
        for one in sel.split(","):
            one = one.strip()
            m = re.fullmatch(r"\.([\w-]+)", one)
            if not m:
                bail(f"unsupported CSS selector {one!r}")
            props = rules.setdefault(m.group(1), {})
            props.update(parse_decl(decl))
        body = body.replace(sel + "{" + decl + "}", "", 1)
    return rules


def parse_decl(decl):
    props = {}
    for part in decl.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            props[k.strip()] = v.strip()
    return props


def norm_hex(v):
    v = v.strip().lower()
    if v in ("none", "transparent"):
        return "none"
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        v = "#" + "".join(c * 2 for c in v[1:])
    if not re.fullmatch(r"#[0-9a-f]{6}", v):
        bail(f"unparseable colour {v!r}")
    if v not in CANON:
        bail(f"colour {v!r} outside the known census")
    return CANON[v]


def num(v):
    return float(re.sub(r"px$", "", v.strip()))


ZERO_AREA_PATH = re.compile(r"^[Mm]\s*[-\d.,\s]+[HhVvLl]\s*[-\d.,\s]+$")

STYLE_PROPS = ("fill", "stroke", "stroke-width", "stroke-miterlimit",
               "fill-opacity", "stroke-opacity", "stroke-dasharray",
               "font-family", "font-size")


def effective(el, css):
    """CSS cascade: presentation attrs < class rules < inline style."""
    props = {k: el.get(k) for k in STYLE_PROPS if el.get(k) is not None}
    for cls in (el.get("class") or "").split():
        if cls not in css:
            bail(f"class {cls!r} has no CSS rule")
        props.update(css[cls])
    props.update(parse_decl(el.get("style") or ""))
    return props


def fold_translate(chain):
    tx = ty = 0.0
    for el in chain:
        t = el.get("transform") or ""
        if not t:
            continue
        m = re.fullmatch(r"\s*translate\(([-\d.]+)[,\s]+([-\d.]+)\)\s*", t)
        if m:
            tx += float(m.group(1))
            ty += float(m.group(2))
        elif tag_of(el) != "text":
            bail(f"unsupported transform {t!r} on <{tag_of(el)}>")
    return tx, ty


def rewrite_svg(svg_text, code):
    """Return (new_svg_text, outline_hex, fill_hex, stats)."""
    root = ET.fromstring(svg_text)
    if tag_of(root) != "svg":
        bail(f"{code}: not an svg root")
    viewbox = root.get("viewBox")
    if viewbox != "0 0 500 500":
        bail(f"{code}: unexpected viewBox {viewbox!r}")
    if "xlink" in svg_text.split(">", 1)[1]:
        pass  # xlink ns decls are fine; assert no xlink: attrs below

    stats = {"deleted_unstyled": 0, "deleted_invisible": 0}

    # 1. strip foreign elements / attributes / <style> capture
    css = {}
    parents = {c: p for p in root.iter() for c in p}
    for el in list(root.iter()):
        if is_foreign(el.tag):
            parents[el].remove(el)
    for el in root.iter():
        for a in list(el.attrib):
            if is_foreign(a) or a.endswith("}space"):
                del el.attrib[a]
            elif "xlink" in a:
                bail(f"{code}: xlink attribute in use")
    root.attrib.pop("style", None)
    parents = {c: p for p in root.iter() for c in p}
    for el in list(root.iter()):
        if tag_of(el) == "style":
            css.update(parse_css("".join(el.itertext())))
            parents[el].remove(el)
    for el in list(root.iter()):
        if tag_of(el) == "defs" and len(el) == 0:
            parents[el].remove(el)

    # 2. resolve effective styling, delete invisible elements
    parents = {c: p for p in root.iter() for c in p}
    resolved = {}
    for el in list(root.iter()):
        t = tag_of(el)
        if t not in DRAWABLE:
            continue
        props = effective(el, css)
        if t == "tspan":
            resolved[el] = props   # style like text; never delete
            continue
        raw_unstyled = (not el.get("class") and not el.get("style")
                        and "fill" not in el.attrib
                        and "stroke" not in el.attrib)
        stroke = props.get("stroke", "none").strip().lower()
        fill = props.get("fill", "").strip().lower() or "#000000"
        no_stroke = stroke in ("", "none")
        zero_area = (t == "line" or
                     (t == "path" and
                      ZERO_AREA_PATH.fullmatch(el.get("d", "").strip())
                      is not None))
        if no_stroke and (fill == "none" or zero_area):
            parents[el].remove(el)
            key = "deleted_unstyled" if raw_unstyled else "deleted_invisible"
            stats[key] += 1
            continue
        resolved[el] = props
    for el in list(root.iter()):
        if tag_of(el) == "g" and not any(
                tag_of(d) in DRAWABLE for d in el.iter() if d is not el):
            parents = {c: p for p in root.iter() for c in p}
            if el in parents:
                parents[el].remove(el)

    # 3. per-symbol main stroke width (mode of widths in the main band)
    widths = {}
    for el, props in resolved.items():
        if props.get("stroke", "none").lower() not in ("", "none"):
            w = num(props.get("stroke-width", "1"))
            if MAIN_W_LO <= w <= MAIN_W_HI:
                widths[w] = widths.get(w, 0) + 1
    main_w = None
    if widths:
        main_w = max(sorted(widths), key=lambda w: (widths[w], w))
        if SNAP_15_LO <= main_w <= SNAP_15_HI:
            main_w = 15.0

    # 4. relocate FAP digit text into the canvas
    if code in TEXT_RELOCATE:
        target_x, target_y = TEXT_RELOCATE[code]
        moved = 0
        for el in root.iter():
            if tag_of(el) != "text":
                continue
            chain = []
            p = el
            while p in parents:
                p = parents[p]
                chain.append(p)
            ptx, pty = fold_translate(chain)
            el.set("transform", "matrix(1 0 0 1 %g %g)"
                   % (target_x - ptx, target_y - pty))
            moved += 1
        if moved != 1:
            bail(f"{code}: expected 1 digit text, moved {moved}")

    # 5. delete inherited labels on clone variants
    if code in TEXT_DELETE:
        parents = {c: p for p in root.iter() for c in p}
        removed = 0
        for el in list(root.iter()):
            if tag_of(el) == "text":
                parents[el].remove(el)
                resolved.pop(el, None)
                removed += 1
        if not removed:
            bail(f"{code}: no inherited <text> to delete")

    # 6. normalize + parameterize as presentation attributes
    strokes, fills = set(), set()
    for el, props in list(resolved.items()):
        if el not in [e for e in root.iter()]:
            continue
        for a in ("class", "style"):
            el.attrib.pop(a, None)
        for k in STYLE_PROPS:
            el.attrib.pop(k, None)
        is_tspan = tag_of(el) == "tspan"
        stroke = props.get("stroke", "none").strip().lower()
        zero_area = (tag_of(el) == "line" or
                     (tag_of(el) == "path" and
                      ZERO_AREA_PATH.fullmatch(el.get("d", "").strip())
                      is not None))
        if is_tspan and "fill" not in props:
            fill = None            # inherit from parent <text>
        elif zero_area:
            fill = "none"          # a fill can never paint on zero area
        else:
            fill = props.get("fill", "").strip().lower() or "#000000"
        if is_tspan and "stroke" not in props:
            stroke = "none"
        if stroke not in ("", "none"):
            c = norm_hex(stroke)
            strokes.add(c)
            el.set("stroke", "param(outline) " + c)
            w = num(props.get("stroke-width", "1"))
            if SNAP_15_LO <= w <= SNAP_15_HI:
                w = 15.0
            if main_w is not None and abs(w - main_w) <= 1.7:
                el.set("stroke-width", "param(outline-width) %g" % main_w)
            else:
                el.set("stroke-width", "%g" % w)
        if fill is None:
            pass
        elif fill == "none":
            el.set("fill", "none")
        else:
            c = norm_hex(fill)
            fills.add(c)
            el.set("fill", "param(fill) " + c)
        if tag_of(el) == "text":
            fam = props.get("font-family", "").strip().strip("'\"")
            if fam:
                el.set("font-family", fam)
            if props.get("font-size"):
                el.set("font-size", props["font-size"])
        ml = props.get("stroke-miterlimit")
        if ml:
            el.set("stroke-miterlimit", ml)
    if len(strokes) > 1 or len(fills) > 1:
        bail(f"{code}: multiple colours survive "
             f"(strokes {strokes}, fills {fills})")
    outline_hex = next(iter(strokes), BLACK)
    fill_hex = next(iter(fills), BLACK)

    # 7. variant modifier glyphs (viewport coordinates)
    if code in VARIANTS:
        g = ET.SubElement(root, "{%s}g" % SVG_NS, {"id": "lgs-variant"})
        for spec in VARIANTS[code]:
            el = ET.SubElement(g, "{%s}%s" % (SVG_NS, spec["tag"]))
            if spec.get("solid"):
                el.set("fill", "param(fill) " + fill_hex)
                el.set("stroke", "none")
            else:
                el.set("fill", "none")
                el.set("stroke", "param(outline) " + outline_hex)
                sw = float(spec.get("sw", "15"))
                if main_w is not None and abs(sw - main_w) <= 3.5:
                    el.set("stroke-width",
                           "param(outline-width) %g" % main_w)
                else:
                    el.set("stroke-width", "%g" % sw)
            for k in ("d", "points", "transform"):
                if k in spec:
                    el.set(k, spec[k])

    # 8. family rescale wrapper so a uniform 30 pt reproduces footprints
    if code in FAC_FAMILY or code in FAP_FAMILY:
        if code in FAC_FAMILY:
            f, ax, ay, tx_target = FAC_SCALE, 250.0, 250.0, 250.0
        else:
            f = FAP_SCALE
            ax, ay = strike_line_centre(root)
            tx_target = 250.0
        tx = tx_target - f * ax
        ty = ay - f * ay
        wrap = ET.Element("{%s}g" % SVG_NS,
                          {"id": "lgs-rescale",
                           "transform": "translate(%.4g,%.4g) scale(%.6g)"
                                        % (tx, ty, f)})
        for child in list(root):
            root.remove(child)
            wrap.append(child)
        root.append(wrap)

    ET.register_namespace("", SVG_NS)
    out = ET.tostring(root, encoding="unicode")
    ET.fromstring(out)                       # self-check
    if 'viewBox="0 0 500 500"' not in out:
        bail(f"{code}: viewBox lost")
    return out, outline_hex, fill_hex, stats


def strike_line_centre(root):
    """Viewport centre of the widest horizontal stroked path."""
    parents = {c: p for p in root.iter() for c in p}
    best = None
    for el in root.iter():
        if tag_of(el) != "path" or not (el.get("stroke") or "").startswith(
                "param(outline)"):
            continue
        d = el.get("d", "").replace(" ", "")
        m = re.fullmatch(r"[Mm]([-\d.]+),([-\d.]+)[hH]([-\d.]+)", d)
        if not m:
            continue
        x, y, h = (float(m.group(i)) for i in (1, 2, 3))
        x2 = x + h if "h" in d else h
        chain = []
        p = el
        while p in parents:
            p = parents[p]
            chain.append(p)
        tx, ty = fold_translate(chain)
        width = abs(x2 - x)
        if width >= 350 and (best is None or width > best[0]):
            best = (width, (x + x2) / 2 + tx, y + ty)
    if best is None:
        bail("no strike line found for FAP-family rescale")
    return best[1], best[2]


def qgis_color(hexc):
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return "%d,%d,%d,255,rgb:%r,%r,%r,1" % (r, g, b, r / 255, g / 255, b / 255)


def svg_markers(renderer_root):
    for layer in renderer_root.iter("layer"):
        if layer.get("class") == "SvgMarker":
            yield layer


def options_of(layer):
    return {o.get("name"): o for o in layer.find("Option").findall("Option")}


def decoded(opts):
    v = opts["name"].get("value") or ""
    if not v.startswith("base64:"):
        bail("SvgMarker without embedded base64 svg")
    return base64.b64decode(v[7:]).decode("utf-8")


def dd_angle_count(renderer_root):
    """Markers whose data-defined angle references DipDirection (84 bind
    it as a field, BAX + FAX2Z as an equivalent expression)."""
    n = 0
    for layer in svg_markers(renderer_root):
        if any(o.get("name") in ("field", "expression")
               and "DipDirection" in (o.get("value") or "")
               for o in layer.iter("Option")):
            n += 1
    return n


def process_fieldnotebook(qml, dump):
    rm = re.search(r"<renderer-v2\b.*?</renderer-v2>", qml, re.S)
    if not rm:
        bail("FieldNotebook renderer-v2 not found")
    rend = ET.fromstring(rm.group(0))
    cats = rend.find("categories").findall("category")
    symbols = rend.find("symbols").findall("symbol")
    if len(cats) != 102 or len(symbols) != 102:
        bail(f"expected 102 categories/symbols, got {len(cats)}/{len(symbols)}")
    for c in cats:                       # L1-L5 -> LNI1-LNI5 (no-op if done)
        new = RENAME.get(c.get("value"))
        if new:
            c.set("value", new)
            c.set("label", RENAME_LABEL[new])
    code_of = {c.get("symbol"): c.get("value") for c in cats}

    markers = []
    for sym in symbols:
        lst = [l for l in sym.iter("layer") if l.get("class") == "SvgMarker"]
        if len(lst) > 1:
            bail(f"symbol {sym.get('name')}: multiple SvgMarker layers")
        for l in lst:
            markers.append((code_of.get(sym.get("name")), l))
    if len(markers) != 86:
        bail(f"expected 86 SvgMarkers, got {len(markers)}")
    n_param = sum(1 for _, l in markers if "param(" in decoded(options_of(l)))
    if n_param == 86:
        print("FieldNotebook: already applied - verifying invariants")
        verify_fieldnotebook(rend, markers)
        return qml, False
    if n_param != 0:
        bail(f"partial parameterization state: {n_param}/86")

    if dd_angle_count(rend) != 86:
        bail("DipDirection angle property not on all 86 markers (pre)")

    totals = {"deleted_unstyled": 0, "deleted_invisible": 0}
    originals = {code: decoded(options_of(layer)) for code, layer in markers}
    for code, layer in markers:
        opts = options_of(layer)
        before = originals[CLONE_SOURCE.get(code, code)]
        after, outline_hex, fill_hex, stats = rewrite_svg(before, code)
        expect = EXPECT_ACCENT.get(code, BLACK)
        if outline_hex != expect or fill_hex != expect:
            bail(f"{code}: colours {outline_hex}/{fill_hex}, expected {expect}")
        opts["name"].set("value", "base64:" + base64.b64encode(
            after.encode("utf-8")).decode("ascii"))
        opts["color"].set("value", qgis_color(fill_hex))
        opts["outline_color"].set("value", qgis_color(outline_hex))
        opts["size"].set("value", SIZE)
        opts["outline_width"].set("value", OUTLINE_W)
        opts["outline_width_unit"].set("value", "Point")
        for k in totals:
            totals[k] += stats[k]
        if dump:
            dump_pair(dump, code, before, after)
    if totals["deleted_unstyled"] != 40:
        bail(f"unstyled deletions {totals['deleted_unstyled']}, expected 40")
    print(f"FieldNotebook: 86 markers rewritten "
          f"(deleted {totals['deleted_unstyled']} unstyled + "
          f"{totals['deleted_invisible']} styled-invisible elements)")

    verify_fieldnotebook(rend, markers)
    new_rend = ET.tostring(rend, encoding="unicode")
    return qml[:rm.start()] + new_rend + qml[rm.end():], True


def verify_fieldnotebook(rend, markers):
    groups = [("CT", "FB", "LAY", "DYK"), ("FO", "CLV", "SCR", "GSN"),
              ("LNI", "LNI1", "LNI2", "LNI3", "LNI4", "LNI5"),
              ("STR", "SLK", "SLF"),
              ("SZC", "MYL", "SZBDY"), ("FAP", "FAPCR"), ("FAC", "FACSP")]
    svgs = {}
    n_text = 0
    for code, layer in markers:
        opts = options_of(layer)
        svg = decoded(opts)
        svgs[code] = svg
        assert "param(" in svg, code
        assert "<style" not in svg and "class=" not in svg, code
        assert not any(f in svg for f in FOREIGN), code
        for h in set(re.findall(r"#[0-9a-fA-F]{3,6}", svg)):
            assert h.upper() in {"#131313", "#1E90FF", "#FF00FF",
                                 "#FFA500", "#32CD32", "#FF0000"}, (code, h)
        if "<text" in svg:
            n_text += 1
        if code in VARIANTS:
            assert "lgs-variant" in svg, code
        if code in FAC_FAMILY or code in FAP_FAMILY:
            assert "lgs-rescale" in svg, code
        assert opts["size"].get("value") == SIZE, code
        assert opts["outline_width"].get("value") == OUTLINE_W, code
    assert n_text == 36, f"text in {n_text} svgs, expected 36"
    for grp in groups:
        digests = {c: hashlib.md5(svgs[c].encode()).hexdigest() for c in grp}
        assert len(set(digests.values())) == len(grp), digests
    assert dd_angle_count(rend) == 86, "DipDirection angle lost"
    print("FieldNotebook invariants ok: 86 param'd, 36 with text, "
          "7 groups unique, angles intact")


def process_linework(qml, dump):
    rm = re.search(r"<renderer-v2\b.*?</renderer-v2>", qml, re.S)
    if not rm:
        bail("Linework renderer-v2 not found")
    rend = ET.fromstring(rm.group(0))
    markers = [l for l in svg_markers(rend)]
    if len(markers) != 23:
        bail(f"expected 23 Linework SvgMarkers, got {len(markers)}")
    plain = [l for l in markers if "param(" not in decoded(options_of(l))]
    if not plain:
        print("Linework: already applied (23/23 parameterized)")
        return qml, False
    if len(plain) != 3:
        bail(f"expected 3 unparameterized Linework markers, got {len(plain)}")
    for i, layer in enumerate(plain):
        opts = options_of(layer)
        before = decoded(opts)
        after, outline_hex, fill_hex, stats = rewrite_svg(before, "LW%d" % i)
        if outline_hex != BLACK or fill_hex != BLACK:
            bail(f"Linework marker {i}: unexpected colours")
        opts["name"].set("value", "base64:" + base64.b64encode(
            after.encode("utf-8")).decode("ascii"))
        opts["color"].set("value", qgis_color(fill_hex))
        opts["outline_color"].set("value", qgis_color(outline_hex))
        size = float(opts["size"].get("value"))
        opts["outline_width"].set("value", "%g" % round(15.0 * size / 500, 3))
        opts["outline_width_unit"].set(
            "value", opts["size_unit"].get("value"))
        if dump:
            dump_pair(dump, "LW%d" % i, before, after)
    for layer in svg_markers(rend):
        assert "param(" in decoded(options_of(layer))
    print("Linework: 3 regressed markers parameterized (23/23 now param'd)")
    return qml[:rm.start()] + ET.tostring(rend, encoding="unicode") \
        + qml[rm.end():], True


def dump_pair(dump, code, before, after):
    os.makedirs(dump, exist_ok=True)
    shown = re.sub(r"param\([\w-]+\) ", "", after)
    with open(os.path.join(dump, code + "_before.svg"), "w",
              encoding="utf-8") as f:
        f.write(before)
    with open(os.path.join(dump, code + "_after.svg"), "w",
              encoding="utf-8") as f:
        f.write(shown)


def write_sheet(dump):
    codes = sorted(set(f.split("_")[0] for f in os.listdir(dump)
                       if f.endswith(".svg")))
    rows = []
    for c in codes:
        rows.append(
            '<div class="row"><div class="c">%s</div>'
            '<img src="%s_before.svg"><img src="%s_after.svg"></div>'
            % (c, c, c))
    html = ('<style>body{font-family:monospace;background:#ddd}'
            '.row{display:inline-block;margin:4px;background:#fff;'
            'padding:4px}.c{text-align:center}img{width:96px;height:96px;'
            'border:1px solid #999;background:#fff}</style>' + "".join(rows))
    with open(os.path.join(dump, "contact_sheet.html"), "w",
              encoding="utf-8") as f:
        f.write(html)
    print(f"dump: {len(codes)} before/after pairs + contact_sheet.html")


def main():
    default = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "Template", "LGS_MappingTemplate.gpkg")
    args = [a for a in sys.argv[1:]]
    dump = None
    if "--dump" in args:
        i = args.index("--dump")
        dump = args[i + 1]
        del args[i:i + 2]
    gpkg = args[0] if args else default
    if not os.path.exists(gpkg):
        bail(f"gpkg not found: {gpkg}")
    con = sqlite3.connect(gpkg)
    cur = con.cursor()

    changed = False
    for old, new in sorted(RENAME.items()):        # lookup-table rename
        n_old = cur.execute("SELECT COUNT(*) FROM FieldNotebookCodes "
                            "WHERE Code=?", (old,)).fetchone()[0]
        n_new = cur.execute("SELECT COUNT(*) FROM FieldNotebookCodes "
                            "WHERE Code=?", (new,)).fetchone()[0]
        if (n_old, n_new) == (1, 0):
            cur.execute("UPDATE FieldNotebookCodes SET Code=?, Description=? "
                        "WHERE Code=?", (new, RENAME_LABEL[new], old))
            assert cur.rowcount == 1
            changed = True
            print(f"FieldNotebookCodes: {old} -> {new}")
        elif (n_old, n_new) != (0, 1):
            bail(f"FieldNotebookCodes {old}/{new} state out of step")
    for layer_name, fn in ((FN_LAYER, process_fieldnotebook),
                           (LW_LAYER, process_linework)):
        qml, = cur.execute(
            "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
            (layer_name,)).fetchone()
        new_qml, did = fn(qml, dump)
        if did:
            try:
                ET.fromstring(new_qml)
            except ET.ParseError as exc:
                bail(f"{layer_name}: edited QML no longer parses: {exc}")
            cur.execute(
                "UPDATE layer_styles SET styleQML=? WHERE f_table_name=?",
                (new_qml, layer_name))
            assert cur.rowcount == 1
            changed = True
    con.commit()

    cur.execute("PRAGMA integrity_check")
    print("integrity_check:", cur.fetchone()[0])
    for layer_name in (FN_LAYER, LW_LAYER):
        q, = cur.execute(
            "SELECT styleQML FROM layer_styles WHERE f_table_name=?",
            (layer_name,)).fetchone()
        ET.fromstring(q)
        print(f"QML parses: {layer_name}")
    # post-write round trip: re-run the read-only verifications
    q, = cur.execute("SELECT styleQML FROM layer_styles WHERE f_table_name=?",
                     (FN_LAYER,)).fetchone()
    rend = ET.fromstring(
        re.search(r"<renderer-v2\b.*?</renderer-v2>", q, re.S).group(0))
    code_of = {c.get("symbol"): c.get("value")
               for c in rend.find("categories").findall("category")}
    markers = [(code_of.get(s.get("name")), l)
               for s in rend.find("symbols").findall("symbol")
               for l in s.iter("layer") if l.get("class") == "SvgMarker"]
    verify_fieldnotebook(rend, markers)
    print("round-trip ok" + (" (changes written)" if changed else " (no-op)"))
    if dump:
        write_sheet(dump)
    con.close()


if __name__ == "__main__":
    main()
