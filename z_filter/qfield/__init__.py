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

import json
import os
import re

SIDECAR_SOURCE = os.path.join(os.path.dirname(__file__), "lgs_companion.qml")

_FLAG_MARKERS = {
    "zfilter": "LGS-EXPORT-FLAG:zfilter",
    "scale": "LGS-EXPORT-FLAG:scale",
    "opacity": "LGS-EXPORT-FLAG:opacity",
}

_DATA_MARKERS = {
    "opacitylayers": "LGS-EXPORT-DATA:opacitylayers",
}


def write_sidecar(export_dir, project_stem, zfilter=True, scale=True,
                  opacity=True, opacity_layers=None):
    """Write the companion plugin next to the exported project file.

    export_dir: destination folder (str or Path)
    project_stem: exported project file name without extension
    zfilter / scale / opacity: enable the Z filter / scale display /
        imagery opacity features
    opacity_layers: names of the exported raster layers the opacity
        toggle should act on (baked into the QML as a JSON array)

    Returns the written path. Raises ValueError if a feature-flag or
    data marker is missing from the QML (guards against the markers
    being edited away).
    """
    with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
        text = fh.read()
    for name, enabled in (("zfilter", zfilter), ("scale", scale),
                          ("opacity", opacity)):
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
    for name, value in (("opacitylayers", opacity_layers),):
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
