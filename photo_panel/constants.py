"""
Photo Panel Constants - Style definitions, DPI constants, and cache settings.

Colours are sourced from plugin_theme so the photo panel matches the rest of
the plugin; a fallback palette keeps the module importable standalone.
"""

# Centralized plugin theme (single source of truth for colours)
try:
    from .. import plugin_theme as _theme
except ImportError:
    try:
        import plugin_theme as _theme
    except ImportError:
        class _ThemeFallback:
            PRIMARY = '#34A853'
            PRIMARY_DARK = '#2E9648'
            PRIMARY_DARKER = '#24733A'
            HEADER_START = '#294023'
            HEADER_END = '#4C7A3D'
            ACCENT = '#FF9E00'
            BG_PRIMARY = '#F8F9FA'
            TEXT_PRIMARY = '#202124'
            TEXT_SECONDARY = '#5F6368'
            BORDER = '#E8EAED'
            BORDER_DARK = '#D2D6DB'
            SELECTED_BG = '#E8F5E9'

        _theme = _ThemeFallback()

# Import UI scaling system for DPI-aware interface
try:
    from ..ui_scaling import get_scale_manager
except ImportError:
    try:
        from ui_scaling import get_scale_manager
    except ImportError:
        class DummyScaleManager:
            def dimension(self, x):
                return x
            def font_size(self, x):
                return x
            def spacing(self, x):
                return x
            def icon_size(self, w, h=None):
                from qgis.PyQt.QtCore import QSize
                return QSize(w, h if h else w)
            def margins(self, *args):
                return tuple(args)
            def dialog_size(self, w, h):
                return (w, h)

        def get_scale_manager():
            return DummyScaleManager()


# Plugin settings key
SETTINGS_KEY = "PhotoPanel"

# Cache settings
MAX_CACHE_SIZE = 200
CACHE_CLEANUP_THRESHOLD = 0.8

# Auto-scroll trigger distance (pixels from bottom to auto-load)
AUTO_LOAD_THRESHOLD = 200

# Thumbnail widgets created per event-loop pass (keeps Load All responsive)
THUMB_CHUNK_SIZE = 20

# Debounce delay for search (ms)
SEARCH_DEBOUNCE_MS = 300

# Zoom constants for QGraphicsView
ZOOM_FACTOR = 1.15
ZOOM_MIN = 0.05
ZOOM_MAX = 20.0


def get_default_thumbnail_size():
    """Get DPI-aware default thumbnail size"""
    scale = get_scale_manager()
    return (scale.dimension(160), scale.dimension(120))


def get_scaled_style():
    """Get style constants with DPI-aware scaling applied."""
    scale = get_scale_manager()

    return {
        # Color palette (from plugin_theme)
        'PRIMARY': _theme.PRIMARY,
        'PRIMARY_DARK': _theme.PRIMARY_DARK,
        'PRIMARY_LIGHT': _theme.SELECTED_BG,
        'SECONDARY': _theme.TEXT_SECONDARY,
        'SECONDARY_LIGHT': _theme.BG_PRIMARY,
        'HEADER_START': _theme.HEADER_START,
        'HEADER_END': _theme.HEADER_END,
        'SUCCESS': _theme.PRIMARY_DARKER,
        'ERROR': '#d62828',
        'WARNING': _theme.ACCENT,
        'TEXT_PRIMARY': _theme.TEXT_PRIMARY,
        'TEXT_SECONDARY': _theme.TEXT_SECONDARY,
        'TEXT_LIGHT': _theme.TEXT_SECONDARY,
        'BORDER': _theme.BORDER,
        'BORDER_DARK': _theme.BORDER_DARK,
        # Dark background for the full-size photo viewer (intentionally dark)
        'VIEWER_BG': '#202124',

        # Shadow styles
        'SHADOW_SM': f'0 {scale.dimension(1)}px {scale.dimension(2)}px rgba(0,0,0,0.05)',
        'SHADOW': f'0 {scale.dimension(1)}px {scale.dimension(3)}px rgba(0,0,0,0.1), 0 {scale.dimension(1)}px {scale.dimension(2)}px rgba(0,0,0,0.06)',
        'SHADOW_MD': f'0 {scale.dimension(4)}px {scale.dimension(6)}px rgba(0,0,0,0.1), 0 {scale.dimension(2)}px {scale.dimension(4)}px rgba(0,0,0,0.06)',
        'SHADOW_LG': f'0 {scale.dimension(10)}px {scale.dimension(15)}px rgba(0,0,0,0.1), 0 {scale.dimension(4)}px {scale.dimension(6)}px rgba(0,0,0,0.05)',

        # Spacing (CSS)
        'SPACING_XS': f'{scale.dimension(2)}px',
        'SPACING_SM': f'{scale.dimension(4)}px',
        'SPACING_MD': f'{scale.dimension(8)}px',
        'SPACING_LG': f'{scale.dimension(12)}px',
        'SPACING_XL': f'{scale.dimension(16)}px',
        'SPACING_2XL': f'{scale.dimension(24)}px',

        # Spacing (numeric for Qt)
        'MARGIN_XS': scale.dimension(2),
        'MARGIN_SM': scale.dimension(4),
        'MARGIN_MD': scale.dimension(8),
        'MARGIN_LG': scale.dimension(12),
        'MARGIN_XL': scale.dimension(16),
        'MARGIN_2XL': scale.dimension(24),

        # Border radius
        'RADIUS_SM': f'{scale.dimension(3)}px',
        'RADIUS_MD': f'{scale.dimension(6)}px',
        'RADIUS_LG': f'{scale.dimension(8)}px',
        'RADIUS_XL': f'{scale.dimension(12)}px',

        # Font settings
        'FONT_FAMILY': 'Segoe UI, Arial, sans-serif',
        'FONT_SIZE_XS': f'{scale.font_size(9)}px',
        'FONT_SIZE_SM': f'{scale.font_size(11)}px',
        'FONT_SIZE_MD': f'{scale.font_size(12)}px',
        'FONT_SIZE_LG': f'{scale.font_size(14)}px',
        'FONT_SIZE_XL': f'{scale.font_size(16)}px',
        'FONT_SIZE_2XL': f'{scale.font_size(18)}px',
    }


# Initialize with scaled values (will be called at import time)
STYLE = get_scaled_style()
DEFAULT_THUMBNAIL_SIZE = get_default_thumbnail_size()
