"""
Mining survey data import — bring survey and design files from any supported
format into one GeoPackage the Z Filter panel can drive, and keep it up to
date as new survey data arrives.

Currently reads Surpac strings (.str) with their paired triangulations
(.dtm), producing strings, survey stations and level outlines. Further
formats plug in through mining_import/formats/ and registry.py.

Entry point:
    run(iface, owner=None)   — open (or raise) the import dialog

Nothing qgis-dependent is imported at module scope: plugin startup pays for
this package only when the user actually opens it.
"""


def run(iface, owner=None):
    """Open the mining import dialog. The singleton is stored on `owner`
    (the plugin instance) as `owner.mining_import_dialog` so its lifecycle
    is plugin-owned, mirroring script_reprojectgeopackage.run()."""
    from .dialog import MiningImportDialog

    existing = getattr(owner, "mining_import_dialog", None) if owner else None
    if existing is not None:
        try:
            existing.raise_()
            existing.activateWindow()
            return existing
        except RuntimeError:
            owner.mining_import_dialog = None

    dialog = MiningImportDialog(iface.mainWindow(), owner=owner)
    if owner is not None:
        # Persistent reference to prevent GC; clean up on close.
        dialog.destroyed.connect(
            lambda: setattr(owner, "mining_import_dialog", None))
        owner.mining_import_dialog = dialog

    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog
