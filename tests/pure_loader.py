"""
Shared loader for mining_import's pure-python modules.

Deliberately NOT named test*.py, so unittest discovery ignores it.

The pure layer (ir, registry, scan, merge and everything under formats/) must
stay importable without QGIS, which is why those modules reach each other
through the dual-import idiom: relative first, flat fallback. Putting
mining_import/ on sys.path is what makes the flat fallback resolve, so a
module loaded by file path here can still find its siblings.
"""

import importlib.util
import os
import sys

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PACKAGE_ROOT = os.path.join(PLUGIN_ROOT, 'mining_import')

for _path in (PACKAGE_ROOT, os.path.join(PACKAGE_ROOT, 'formats')):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def load(relative_path, name=None):
    """Load a module under mining_import/ by path, without importing qgis.

    relative_path is relative to mining_import/, e.g. 'formats/surpac.py'.
    Loaded modules are registered in sys.modules under their bare name so a
    sibling's flat-fallback import finds the same instance.
    """
    full = os.path.join(PACKAGE_ROOT, relative_path.replace('/', os.sep))
    if name is None:
        name = os.path.splitext(os.path.basename(relative_path))[0]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, full)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def pure_module_paths():
    """Every module that must remain importable without QGIS."""
    paths = ['ir.py', 'registry.py', 'scan.py', 'merge.py']
    formats_dir = os.path.join(PACKAGE_ROOT, 'formats')
    for fname in sorted(os.listdir(formats_dir)):
        if fname.endswith('.py') and fname != '__init__.py':
            paths.append('formats/' + fname)
    return paths
