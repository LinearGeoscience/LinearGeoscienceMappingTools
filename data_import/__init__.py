"""
Import Mapping Data — bring an existing mapping dataset into an LGS template.

Replaces the old "Append Mapping Data" tool (script_adddata). That tool copied
rows; this one performs a migration, because the template has moved: layers were
renumbered, fields were added, and code lists were audited, renamed and retired.

The design rule throughout is that the DESTINATION describes itself. Nothing here
hardcodes a field list or a code list — `domain.read_gpkg_model()` reads the
destination's own ValueRelation/ValueMap widget configuration, cascade filters,
default-value expressions and constraints, so the importer stays correct the next
time the template changes.

The second rule is that the destination's schema is immutable. No column is ever
added to a target layer. A source field that has nowhere to go is dropped or
folded into Comments — never grafted on, which is what silently corrupted
projects (and the shipped template) before.
"""

__version__ = "1.0.0"


def run_import_dialog(iface):
    """Open the Import Mapping Data wizard. Imported lazily: the wizard pulls in
    QtWidgets, which the pure modules under this package must not."""
    from .wizard.dialog import run_import_dialog as _run
    return _run(iface)


__all__ = ['run_import_dialog']
