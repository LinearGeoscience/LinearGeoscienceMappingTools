# -*- coding: utf-8 -*-

"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsFeatureSink,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsWkbTypes,
)
from ..core.spline_interp import interpolate_closed_ring

SINGLE_POLYGON_TYPES = (
    QgsWkbTypes.Polygon,
    QgsWkbTypes.PolygonM,
    QgsWkbTypes.PolygonZ,
    QgsWkbTypes.PolygonZM,
    QgsWkbTypes.Polygon25D,
    QgsWkbTypes.PolygonGeometry,
)

from ..core.utils import DEFAULT_TIGHTNESS, DEFAULT_TOLERANCE, DEFAULT_MAX_SEGMENTS, SETTINGS_NAME


class Polygons2SplinesProcessingAlgorithm(QgsProcessingAlgorithm):
    """
    This algorithm converts polygon geometry to smoothed splines.
    """

    INPUT = "INPUT"
    TENSION = "TENSION"
    TOLERANCE = "TOLERANCE"
    MAX_SEGMENTS = "MAX_SEGMENTS"
    OUTPUT = "OUTPUT"

    def tr(self, string):
        """
        Returns a translatable string with the self.tr() function.
        """
        return QCoreApplication.translate("Map Cleaning Toolkit", string)

    def createInstance(self):
        return Polygons2SplinesProcessingAlgorithm()

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return "polygons2splines"

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr("Polygons to splines (smooth)")

    def helpUrl(self):
        return "https://github.com/LinearGeoscience/LinearGeoscienceMappingTools"

    def shortHelpString(self):
        help_str = """
        Smooth polygon geometries using splines (closed rings of straight lines).

        A modified <a href=https://en.wikipedia.org/wiki/Cubic_Hermite_spline>cubic Hermite spline interpolator</a> is used to obtain continuous piecewise third-degree polynomials between knots (known polygon vertices).
        Each piece is converted to a chain of lines which is then simplified with <a href=https://en.wikipedia.org/wiki/Ramer%E2%80%93Douglas%E2%80%93Peucker_algorithm>Douglas-Peuker algorithm</a>.

        This algorithm treats polygon rings as closed loops, ensuring smooth transitions at the start/end point.
        Both exterior and interior rings (holes) are processed independently.

        <i>z</i> and <i>m</i> values are currently not supported for polygons.

        Parameters:
         * Tightness or tension - can be interpreted as the length of the curve tangent at digitized points, must be in interval [0,1]
         * Tolerance for Douglas-Peuker simplification algorithm - the smaller it is, the more segmented is the resulting polygon.
         * Max number of spline segments - initial number of spline segments interpolated between vertices. This is then simplified.
        """
        return self.tr(help_str)

    def initAlgorithm(self, config=None):
        tension = QSettings().value(SETTINGS_NAME + "/tightness", DEFAULT_TIGHTNESS, float)
        tolerance = QSettings().value(SETTINGS_NAME + "/tolerance", DEFAULT_TOLERANCE, float)
        max_segments = QSettings().value(SETTINGS_NAME + "/max_segments", DEFAULT_MAX_SEGMENTS, float)

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT, self.tr("Input layer"), [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TENSION,
                self.tr("Tension parameter"),
                QgsProcessingParameterNumber.Double,
                tension,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TOLERANCE,
                self.tr("Tolerance parameter"),
                QgsProcessingParameterNumber.Double,
                tolerance,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_SEGMENTS,
                self.tr("Max number of spline segments between vertices"),
                QgsProcessingParameterNumber.Integer,
                max_segments,
            )
        )
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr("Smoothed polygons layer")))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        # Check if the input layer is single type geometry
        if source.wkbType() not in SINGLE_POLYGON_TYPES:
            raise QgsProcessingException(
                "Wrong input geometry type (multi or not polygon). Convert it to single polygon type and try again.")

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, source.fields(), source.wkbType(), source.sourceCrs()
        )
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        tension = self.parameterAsDouble(
            parameters,
            self.TENSION,
            context,
        )
        tolerance = self.parameterAsDouble(
            parameters,
            self.TOLERANCE,
            context,
        )
        max_segments = self.parameterAsInt(
            parameters,
            self.MAX_SEGMENTS,
            context,
        )

        total = 100.0 / source.featureCount() if source.featureCount() else 0
        features = source.getFeatures()

        for current, feature in enumerate(features):
            if feedback.isCanceled():
                break

            feedback.pushInfo(f"\nProcessing feature id={feature.id()}")
            cur_geom = feature.geometry()

            if cur_geom.isNull() or cur_geom.isEmpty():
                feedback.pushInfo(f"  Skipping null/empty geometry")
                sink.addFeature(feature, QgsFeatureSink.FastInsert)
                continue

            try:
                # Get polygon parts
                if cur_geom.isMultipart():
                    feedback.pushInfo(f"  WARNING: Multipart geometry detected - processing first part only")
                    polygons = cur_geom.asMultiPolygon()
                    if not polygons:
                        sink.addFeature(feature, QgsFeatureSink.FastInsert)
                        continue
                    polygon = polygons[0]  # Take first polygon
                else:
                    polygon = cur_geom.asPolygon()

                if not polygon:
                    feedback.pushInfo(f"  Skipping - cannot extract polygon")
                    sink.addFeature(feature, QgsFeatureSink.FastInsert)
                    continue

                # Process exterior ring
                exterior_ring = polygon[0]
                if len(exterior_ring) < 4:
                    feedback.pushInfo(f"  Skipping - exterior ring has too few vertices ({len(exterior_ring)})")
                    sink.addFeature(feature, QgsFeatureSink.FastInsert)
                    continue

                feedback.pushInfo(f"  Exterior ring: {len(exterior_ring)} vertices")
                smoothed_exterior = interpolate_closed_ring(exterior_ring, tolerance, tension, max_segments)

                if len(smoothed_exterior) < 4:
                    feedback.pushInfo(f"  WARNING: Smoothed exterior ring too small, using original")
                    smoothed_exterior = exterior_ring

                # Process interior rings (holes)
                smoothed_interiors = []
                if len(polygon) > 1:
                    feedback.pushInfo(f"  Processing {len(polygon) - 1} interior rings (holes)")
                    for hole_idx, interior_ring in enumerate(polygon[1:], 1):
                        if len(interior_ring) < 4:
                            feedback.pushInfo(f"    Hole {hole_idx}: too few vertices ({len(interior_ring)}), keeping original")
                            smoothed_interiors.append(interior_ring)
                            continue

                        feedback.pushInfo(f"    Hole {hole_idx}: {len(interior_ring)} vertices")
                        smoothed_interior = interpolate_closed_ring(interior_ring, tolerance, tension, max_segments)

                        if len(smoothed_interior) < 4:
                            feedback.pushInfo(f"    Hole {hole_idx}: smoothing failed, keeping original")
                            smoothed_interiors.append(interior_ring)
                        else:
                            smoothed_interiors.append(smoothed_interior)

                # Construct smoothed polygon
                smoothed_polygon = [smoothed_exterior] + smoothed_interiors
                spline_geom = QgsGeometry.fromPolygonXY(smoothed_polygon)

                # Validate geometry
                if not spline_geom.isGeosValid():
                    feedback.pushInfo(f"  WARNING: Invalid geometry after smoothing, using original")
                    sink.addFeature(feature, QgsFeatureSink.FastInsert)
                    continue

                # Create output feature
                spline_feat = QgsFeature(feature)
                spline_feat.setGeometry(spline_geom)
                sink.addFeature(spline_feat, QgsFeatureSink.FastInsert)

                feedback.pushInfo(f"  Success: smoothed to {len(smoothed_exterior)} exterior vertices")

            except Exception as e:
                feedback.pushInfo(f"  ERROR processing feature {feature.id()}: {e}")
                # Keep original on error
                sink.addFeature(feature, QgsFeatureSink.FastInsert)

            feedback.setProgress(int(current * total))

        return {self.OUTPUT: dest_id}
