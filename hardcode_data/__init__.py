"""Hardcode Data & Update Legends — combined data hardcoding, legend
filling, data-quality reporting and UUID checking tool."""


def run(iface):
    """Entry point called from mainplugin.py."""
    from .dialog import HardcodeDataDialog
    dialog = HardcodeDataDialog(iface.mainWindow())
    dialog.exec()
