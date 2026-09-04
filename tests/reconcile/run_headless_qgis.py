#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bootstrap a headless QgsApplication and exec one QGIS-bound suite.

Usage:  C:\\OSGeo4W\\bin\\python-qgis-ltr.bat run_headless_qgis.py <test_file.py>

The console suites assume QGIS is already up; this provides the same
environment without the GUI so they can run from a terminal. Exits with the
suite's own exit code.
"""

import os
import sys

from qgis.core import QgsApplication

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", ""), True)
app = QgsApplication([], False)
app.initQgis()

target = sys.argv[1]
sys.argv = [target]
code = 0
try:
    src = open(target, "r", encoding="utf-8").read()
    g = {"__name__": "__main__", "__file__": os.path.abspath(target)}
    try:
        exec(compile(src, target, "exec"), g)
    except SystemExit as se:
        code = int(se.code or 0)
finally:
    app.exitQgis()
sys.exit(code)
