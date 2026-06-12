"""
UI Scaling Manager for Linear Geoscience Mapping Tools
Provides DPI-aware scaling for all UI elements across different screen resolutions and scaling settings.

This module ensures consistent UI appearance across different devices and display settings,
from 1080p to 4K displays, and handles Windows scaling settings properly.
"""

from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsMessageLog, Qgis


class UIScaleManager:
    """
    Singleton class for managing UI scaling across the plugin.

    Detects system DPI and provides methods to scale all UI dimensions,
    fonts, icons, and spacing consistently.
    """

    _instance = None
    _initialized = False

    # Base DPI for reference (standard Windows DPI)
    BASE_DPI = 96.0

    # Minimum and maximum scale factors for safety
    MIN_SCALE_FACTOR = 0.5
    MAX_SCALE_FACTOR = 3.0

    def __new__(cls):
        """Singleton pattern implementation"""
        if cls._instance is None:
            cls._instance = super(UIScaleManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the scale manager with current screen DPI"""
        if not UIScaleManager._initialized:
            self._detect_scaling()
            UIScaleManager._initialized = True
            self._log_scaling_info()

    def _detect_scaling(self):
        """Detect the current screen DPI and calculate scale factor"""
        try:
            app = QApplication.instance()
            if app is None:
                # Fallback if no QApplication instance exists
                self.scale_factor = 1.0
                self.logical_dpi = self.BASE_DPI
                self.physical_dpi = self.BASE_DPI
                QgsMessageLog.logMessage(
                    "No QApplication instance found, using default scale factor of 1.0",
                    "LinearGeoscience",
                    Qgis.Warning
                )
                return

            # Get primary screen
            screen = app.primaryScreen()
            if screen is None:
                self.scale_factor = 1.0
                self.logical_dpi = self.BASE_DPI
                self.physical_dpi = self.BASE_DPI
                QgsMessageLog.logMessage(
                    "No primary screen found, using default scale factor of 1.0",
                    "LinearGeoscience",
                    Qgis.Warning
                )
                return

            # Get logical DPI (accounts for Windows scaling)
            self.logical_dpi = screen.logicalDotsPerInchX()

            # Get physical DPI
            self.physical_dpi = screen.physicalDotsPerInchX()

            # Calculate scale factor based on logical DPI
            # Logical DPI already includes OS scaling settings
            self.scale_factor = self.logical_dpi / self.BASE_DPI

            # Clamp scale factor to reasonable bounds
            if self.scale_factor < self.MIN_SCALE_FACTOR:
                QgsMessageLog.logMessage(
                    f"Scale factor {self.scale_factor:.2f} below minimum, clamping to {self.MIN_SCALE_FACTOR}",
                    "LinearGeoscience",
                    Qgis.Warning
                )
                self.scale_factor = self.MIN_SCALE_FACTOR
            elif self.scale_factor > self.MAX_SCALE_FACTOR:
                QgsMessageLog.logMessage(
                    f"Scale factor {self.scale_factor:.2f} above maximum, clamping to {self.MAX_SCALE_FACTOR}",
                    "LinearGeoscience",
                    Qgis.Warning
                )
                self.scale_factor = self.MAX_SCALE_FACTOR

            # Store device pixel ratio for additional scaling needs
            self.device_pixel_ratio = screen.devicePixelRatio()

        except Exception as e:
            # Fallback to no scaling on error
            self.scale_factor = 1.0
            self.logical_dpi = self.BASE_DPI
            self.physical_dpi = self.BASE_DPI
            self.device_pixel_ratio = 1.0
            QgsMessageLog.logMessage(
                f"Error detecting screen DPI: {str(e)}. Using scale factor of 1.0",
                "LinearGeoscience",
                Qgis.Critical
            )

    def _log_scaling_info(self):
        """Log detected scaling information for debugging"""
        QgsMessageLog.logMessage(
            f"UI Scaling initialized - DPI: {self.logical_dpi:.1f}, "
            f"Physical DPI: {self.physical_dpi:.1f}, "
            f"Scale Factor: {self.scale_factor:.2f}, "
            f"Device Pixel Ratio: {self.device_pixel_ratio:.2f}",
            "LinearGeoscience",
            Qgis.Info
        )

    def dimension(self, base_pixels):
        """
        Scale a dimension (width, height, margin, padding, etc.)

        Args:
            base_pixels (int or float): Base dimension in pixels at 96 DPI

        Returns:
            int: Scaled dimension in pixels
        """
        if base_pixels is None:
            return None
        return int(round(base_pixels * self.scale_factor))

    def font_size(self, base_size):
        """
        Scale a font size

        Args:
            base_size (int or float): Base font size in points at 96 DPI

        Returns:
            int: Scaled font size in points
        """
        if base_size is None:
            return None
        # Font sizes may need slightly different scaling
        # Using 90% of full scale to prevent overly large fonts
        return int(round(base_size * self.scale_factor * 0.95))

    def icon_size(self, width, height=None):
        """
        Scale icon dimensions

        Args:
            width (int): Base width in pixels at 96 DPI
            height (int, optional): Base height in pixels. If None, uses width (square icon)

        Returns:
            QSize: Scaled icon size
        """
        if height is None:
            height = width

        scaled_width = self.dimension(width)
        scaled_height = self.dimension(height)

        return QSize(scaled_width, scaled_height)

    def margins(self, top, right=None, bottom=None, left=None):
        """
        Scale margins (top, right, bottom, left)

        Args:
            top (int): Top margin at 96 DPI
            right (int, optional): Right margin. If None, uses top
            bottom (int, optional): Bottom margin. If None, uses top
            left (int, optional): Left margin. If None, uses right

        Returns:
            tuple: (scaled_top, scaled_right, scaled_bottom, scaled_left)
        """
        if right is None:
            right = top
        if bottom is None:
            bottom = top
        if left is None:
            left = right

        return (
            self.dimension(top),
            self.dimension(right),
            self.dimension(bottom),
            self.dimension(left)
        )

    def spacing(self, base_spacing):
        """
        Scale spacing between elements

        Args:
            base_spacing (int): Base spacing in pixels at 96 DPI

        Returns:
            int: Scaled spacing in pixels
        """
        return self.dimension(base_spacing)

    def dialog_size(self, width, height):
        """
        Scale dialog/window dimensions

        Args:
            width (int): Base width in pixels at 96 DPI
            height (int): Base height in pixels at 96 DPI

        Returns:
            tuple: (scaled_width, scaled_height)
        """
        return (self.dimension(width), self.dimension(height))

    def stylesheet_dimension(self, base_pixels, unit='px'):
        """
        Get scaled dimension as string for stylesheet

        Args:
            base_pixels (int): Base dimension in pixels at 96 DPI
            unit (str): CSS unit (default: 'px')

        Returns:
            str: Scaled dimension with unit (e.g., "16px")
        """
        return f"{self.dimension(base_pixels)}{unit}"

    def get_scale_factor(self):
        """
        Get the current scale factor

        Returns:
            float: Current scale factor
        """
        return self.scale_factor

    def get_logical_dpi(self):
        """
        Get the logical DPI (includes OS scaling)

        Returns:
            float: Logical DPI
        """
        return self.logical_dpi

    def get_physical_dpi(self):
        """
        Get the physical screen DPI

        Returns:
            float: Physical DPI
        """
        return self.physical_dpi

    def refresh_scaling(self):
        """
        Refresh scaling detection (useful if display settings change)
        This should be called if the plugin detects a screen change event.
        """
        old_factor = self.scale_factor
        self._detect_scaling()

        if abs(old_factor - self.scale_factor) > 0.01:
            QgsMessageLog.logMessage(
                f"Display scaling changed from {old_factor:.2f} to {self.scale_factor:.2f}",
                "LinearGeoscience",
                Qgis.Info
            )
            return True
        return False


# Global singleton instance accessor
_scale_manager_instance = None


def get_scale_manager():
    """
    Get the global UIScaleManager instance.

    Returns:
        UIScaleManager: Singleton instance of the scale manager
    """
    global _scale_manager_instance
    if _scale_manager_instance is None:
        _scale_manager_instance = UIScaleManager()
    return _scale_manager_instance


# Convenience functions for quick access
def scale_dim(pixels):
    """Convenience function to scale a dimension"""
    return get_scale_manager().dimension(pixels)


def scale_font(size):
    """Convenience function to scale a font size"""
    return get_scale_manager().font_size(size)


def scale_icon(width, height=None):
    """Convenience function to scale an icon size"""
    return get_scale_manager().icon_size(width, height)


def scale_margins(top, right=None, bottom=None, left=None):
    """Convenience function to scale margins"""
    return get_scale_manager().margins(top, right, bottom, left)


def scale_spacing(spacing):
    """Convenience function to scale spacing"""
    return get_scale_manager().spacing(spacing)
