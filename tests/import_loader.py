"""
Shared loader for data_import's pure-python modules.

Deliberately NOT named test*.py, so unittest discovery ignores it.

domain, scan, derive, plan and the three matchers must stay importable without
QGIS — that is what lets the code-translation ladder be tested against the real
shipped template on any machine, rather than only inside QGIS. They reach each
other and lgs_layers through the dual-import idiom (relative first, flat
fallback); putting both the plugin root and data_import/ on sys.path is what
makes the flat fallback resolve.
"""

import importlib.util
import os
import sys

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PACKAGE_ROOT = os.path.join(PLUGIN_ROOT, 'data_import')

for _path in (PLUGIN_ROOT, PACKAGE_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

TEMPLATE = os.path.join(PLUGIN_ROOT, 'Template', 'LGS_MappingTemplate.gpkg')


def load(relative_path, name=None):
    """Load a module under data_import/ by path, without importing qgis."""
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
    return ['domain.py', 'fuzzy.py', 'match_layers.py', 'match_fields.py',
            'match_values.py', 'derive.py', 'scan.py', 'plan.py']


def template_model():
    """The shipped template, read once per process."""
    domain = load('domain.py')
    cached = getattr(template_model, '_cached', None)
    if cached is None:
        cached = domain.read_gpkg_model(TEMPLATE)
        template_model._cached = cached
    return cached
