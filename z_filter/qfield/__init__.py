"""
QField side of the LGS companion plugin.

lgs_companion.qml is a QField *project plugin*: QField auto-activates a
.qml file that sits next to the project file and shares its basename.
It bundles two independently-enabled features — the Z (elevation) filter
and the map scale display/lock — because QField allows only ONE sidecar
per project. The exporter calls write_sidecar() to ship it, rewriting the
LGS-EXPORT-FLAG lines to enable exactly the features chosen in the export
dialog.

Pure python (no qgis imports) so tests can load this file directly.
"""

import os
import re

SIDECAR_SOURCE = os.path.join(os.path.dirname(__file__), "lgs_companion.qml")

_FLAG_MARKERS = {
    "zfilter": "LGS-EXPORT-FLAG:zfilter",
    "scale": "LGS-EXPORT-FLAG:scale",
}


def write_sidecar(export_dir, project_stem, zfilter=True, scale=True):
    """Write the companion plugin next to the exported project file.

    export_dir: destination folder (str or Path)
    project_stem: exported project file name without extension
    zfilter / scale: enable the Z filter / scale display features

    Returns the written path. Raises ValueError if a feature-flag marker
    is missing from the QML (guards against the markers being edited away).
    """
    with open(SIDECAR_SOURCE, encoding="utf-8") as fh:
        text = fh.read()
    for name, enabled in (("zfilter", zfilter), ("scale", scale)):
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
    target = os.path.join(str(export_dir), f"{project_stem}.qml")
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return target
