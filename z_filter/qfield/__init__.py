"""
QField side of the Z filter.

zfilter_sidecar.qml is a QField *project plugin*: QField auto-activates a
.qml file that sits next to the project file and shares its basename. The
exporter calls write_sidecar() to ship it with every export, giving the
field crew the same level switching the desktop panel provides.
"""

import os
import shutil

SIDECAR_SOURCE = os.path.join(os.path.dirname(__file__), "zfilter_sidecar.qml")


def write_sidecar(export_dir, project_stem):
    """Copy the sidecar plugin next to the exported project file.

    export_dir: destination folder (str or Path)
    project_stem: exported project file name without extension

    Returns the written path.
    """
    target = os.path.join(str(export_dir), f"{project_stem}.qml")
    shutil.copy2(SIDECAR_SOURCE, target)
    return target
