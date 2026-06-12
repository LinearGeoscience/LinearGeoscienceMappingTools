# __init__.py

def classFactory(iface):
    """
    This is QGIS's entry point for the plugin.
    We import 'LinearGeosciencePluginMain' from mainplugin.py
    and return an instance of it.
    """
    from .mainplugin import LinearGeosciencePluginMain
    return LinearGeosciencePluginMain(iface)
