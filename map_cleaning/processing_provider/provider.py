from qgis.core import QgsProcessingProvider

from .processing_alg import Lines2SplinesProcessingAlgorithm
from .polygons_to_splines_alg import Polygons2SplinesProcessingAlgorithm


class Provider(QgsProcessingProvider):
    def loadAlgorithms(self, *args, **kwargs):
        self.addAlgorithm(Lines2SplinesProcessingAlgorithm())
        self.addAlgorithm(Polygons2SplinesProcessingAlgorithm())

    def id(self, *args, **kwargs):
        """The ID of your plugin, used for identifying the provider."""
        return "linear_geoscience_map_cleaning"

    def name(self, *args, **kwargs):
        """The human friendly name of your plugin in Processing."""
        return self.tr("Map Cleaning Toolkit")

    def icon(self):
        """Should return a QIcon which is used for your provider inside the Processing toolbox."""
        return QgsProcessingProvider.icon(self)
