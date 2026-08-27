"""
QField side of the LGS companion plugin.

lgs_companion.qml is a QField *project plugin*: QField auto-activates a
.qml file that sits next to the project file and shares its basename.
It bundles independently-enabled features — the Z (elevation) filter,
the map scale display/lock and the imagery opacity toggle — because
QField allows only ONE sidecar per project. The exporter calls
write_sidecar() to ship it, rewriting the LGS-EXPORT-FLAG lines to
enable exactly the features chosen in the export dialog and the
LGS-EXPORT-DATA lines to bake in export-time data (raster layer names).

Pure python (no qgis imports) so tests can load this file directly.
"""

import datetime
import hashlib
import json
import os
import re

SIDECAR_SOURCE = os.path.join(os.path.dirname(__file__), "lgs_companion.qml")

_FLAG_MARKERS = {
    "zfilter": "LGS-EXPORT-FLAG:zfilter",
    "scale": "LGS-EXPORT-FLAG:scale",
    "opacity": "LGS-EXPORT-FLAG:opacity",
    "clipping": "LGS-EXPORT-FLAG:clipping",
    "spline": "LGS-EXPORT-FLAG:spline",
    "reshape": "LGS-EXPORT-FLAG:reshape",
    "reverse": "LGS-EXPORT-FLAG:reverse",
    "copyattrs": "LGS-EXPORT-FLAG:copyattrs",
    "merge": "LGS-EXPORT-FLAG:merge",
    "recenterhold": "LGS-EXPORT-FLAG:recenterhold",
    "modetoggle": "LGS-EXPORT-FLAG:modetoggle",
}

_DATA_MARKERS = {
    "opacitylayers": "LGS-EXPORT-DATA:opacitylayers",
    "vectoropacitylayers": "LGS-EXPORT-DATA:vectoropacitylayers",
    "splineparams": "LGS-EXPORT-DATA:splineparams",
    "build": "LGS-EXPORT-DATA:build",
}


def sidecar_build_stamp(source_text, exported_at=None):
    """[date, short-hash] identifying the sidecar shipped to a device.

    The hash is of the UNSTAMPED source, so it identifies the code and not
    the export: two exports of the same sidecar share a hash, and any edit
    to lgs_companion.qml changes it.  Shown in the plugin's Z panel, which
    is the only way to tell which build a tablet is actually running - the
    sidecar reaches the device by file copy, so a stale project looks
    exactly like a fix that did not work.
    """
    digest = hashlib.sha1(source_text.encode("utf-8")).hexdigest()[:8]
    stamped = exported_at or datetime.date.today().isoformat()
    return [stamped, digest]


def write_sidecar(export_dir, project_stem, zfilter=True, scale=True,
                  opacity=True, clipping=True, spline=True, reshape=True,
                  reverse=True, copyattrs=True, merge=True,
                  recenterhold=True, modetoggle=True,
                  opacity_layers=None, vector_layers=None,
                  spline_params=None):
    """Write the companion plugin next to the exported project file.

    export_dir: destination folder (str or Path)
    project_stem: exported project file name without extension
    zfilter / scale / opacity / clipping / spline / reshape / reverse /
    copyattrs / merge / recenterhold / modetoggle:
        enable the Z filter / scale display / layer opacity / polygon
        clip / spline digitizing / multi-polygon reshape / line
        direction reverse / attribute copy / polygon merge / freehand
        recenter-hold / browse-digitise mode-toggle features
    opacity_layers: names of the exported raster layers the opacity
        panel should act on (baked into the QML as a JSON array)
    vector_layers: names of the exported spatial vector layers for the
        opacity panel's Vectors column (same JSON-array baking)
    spline_params: [tightness, tolerance, max_segments] from the desktop
        Map Cleaning settings (empty list keeps the QML defaults)

    Returns the written path. Raises ValueError if a feature-flag or
    data marker is missing from the QML (guards against the markers
    being edited away).
    """
    with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
        text = fh.read()
    # Stamped from the UNMODIFIED source, so the hash tracks the sidecar
    # code rather than this particular export's feature picks.
    build = sidecar_build_stamp(text)
    for name, enabled in (("zfilter", zfilter), ("scale", scale),
                          ("opacity", opacity), ("clipping", clipping),
                          ("spline", spline), ("reshape", reshape),
                          ("reverse", reverse), ("copyattrs", copyattrs),
                          ("merge", merge), ("recenterhold", recenterhold),
                          ("modetoggle", modetoggle)):
        marker = _FLAG_MARKERS[name]
        pattern = re.compile(
            r"^(\s*readonly property bool \w+: )(?:true|false)( // %s)$"
            % re.escape(marker), re.MULTILINE)
        text, count = pattern.subn(
            r"\g<1>%s\g<2>" % ("true" if enabled else "false"), text)
        if count != 1:
            raise ValueError(
                f"sidecar flag marker '{marker}' matched {count} lines "
                f"(expected exactly 1) in {SIDECAR_SOURCE}")
    for name, value in (("opacitylayers", opacity_layers),
                        ("vectoropacitylayers", vector_layers),
                        ("splineparams", spline_params),
                        ("build", build)):
        marker = _DATA_MARKERS[name]
        pattern = re.compile(
            r"^(\s*readonly property var \w+: )\[.*\]( // %s)$"
            % re.escape(marker), re.MULTILINE)
        payload = json.dumps(list(value or []))
        text, count = pattern.subn(
            lambda m, payload=payload: m.group(1) + payload + m.group(2),
            text)
        if count != 1:
            raise ValueError(
                f"sidecar data marker '{marker}' matched {count} lines "
                f"(expected exactly 1) in {SIDECAR_SOURCE}")
    target = os.path.join(str(export_dir), f"{project_stem}.qml")
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return target
