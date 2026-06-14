"""
Plugin Theme - Centralized design tokens and stylesheet generators for the main plugin dialog.

Modeled on photo_panel/constants.py, this module provides a single source of truth for
colors, spacing, typography, and reusable stylesheet functions used by mainplugin.py.
All dimensions are routed through get_scale_manager() for DPI awareness.
"""

try:
    from .ui_scaling import get_scale_manager
except ImportError:
    try:
        from ui_scaling import get_scale_manager
    except ImportError:
        class _DummyScaleManager:
            def dimension(self, x): return x
            def font_size(self, x): return x
            def spacing(self, x): return x
            def icon_size(self, w, h=None):
                from qgis.PyQt.QtCore import QSize
                return QSize(w, h if h else w)
            def margins(self, *args): return tuple(args)
            def dialog_size(self, w, h): return (w, h)

        def get_scale_manager():
            return _DummyScaleManager()


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
PRIMARY = "#34A853"
PRIMARY_DARK = "#2E9648"
PRIMARY_DARKER = "#24733A"

HEADER_START = "#294023"
HEADER_END = "#4C7A3D"

ACCENT = "#FF9E00"
ACCENT_HOVER = "#FFA820"
ACCENT_PRESSED = "#E68900"

QFIELD = "#475569"
QFIELD_HOVER = "#64748B"
QFIELD_PRESSED = "#334155"

RECONCILE = "#34A853"
RECONCILE_HOVER = "#41B662"
RECONCILE_PRESSED = "#2E9648"

BG_PRIMARY = "#F8F9FA"
BG_SIDEBAR = "#FFFFFF"
BG_CARD = "#FFFFFF"

TEXT_PRIMARY = "#202124"
TEXT_SECONDARY = "#5F6368"

BORDER = "#E8EAED"
BORDER_DARK = "#D2D6DB"
HOVER = "#F1F3F4"
SELECTED_BG = "#E8F5E9"

FONT_FAMILY = "Segoe UI, Arial, sans-serif"


# ---------------------------------------------------------------------------
# Scaled token helpers (call these at render time, not import time)
# ---------------------------------------------------------------------------

def _s():
    """Shorthand for the scale manager."""
    return get_scale_manager()


def spacing_xs(): return _s().dimension(2)
def spacing_sm(): return _s().dimension(4)
def spacing_md(): return _s().dimension(8)
def spacing_lg(): return _s().dimension(12)
def spacing_xl(): return _s().dimension(16)
def spacing_2xl(): return _s().dimension(24)

def font_xs(): return _s().font_size(9)
def font_sm(): return _s().font_size(11)
def font_md(): return _s().font_size(12)
def font_lg(): return _s().font_size(14)
def font_xl(): return _s().font_size(16)
def font_2xl(): return _s().font_size(18)
def font_title(): return _s().font_size(24)

def radius_sm(): return _s().dimension(3)
def radius_md(): return _s().dimension(6)
def radius_lg(): return _s().dimension(8)


# ---------------------------------------------------------------------------
# Stylesheet generators
# ---------------------------------------------------------------------------

def nav_button_style():
    """Sidebar navigation button stylesheet (checkable QPushButton)."""
    s = _s()
    pad = s.dimension(8)
    pad_left = s.dimension(12)
    br = radius_sm()
    fs = font_md()
    indicator = s.dimension(3)
    return f"""
        QPushButton {{
            text-align: left;
            background-color: transparent;
            border: none;
            padding: {pad}px {pad}px {pad}px {pad_left}px;
            border-radius: {br}px;
            font-size: {fs}px;
            font-family: {FONT_FAMILY};
            border-left: {indicator}px solid transparent;
        }}
        QPushButton:hover {{
            background-color: {HOVER};
        }}
        QPushButton:checked {{
            background-color: {SELECTED_BG};
            color: {PRIMARY};
            font-weight: bold;
            border-left: {indicator}px solid {PRIMARY};
        }}
    """


def quick_access_button_style():
    """Quick-access launch button in sidebar (outlined green card)."""
    s = _s()
    pad_v = s.dimension(8)
    pad_h = s.dimension(10)
    br = radius_sm()
    fs = font_md()
    return f"""
        QPushButton {{
            text-align: left;
            background-color: {BG_CARD};
            border: 1px solid {PRIMARY};
            color: {PRIMARY_DARK};
            font-weight: bold;
            padding: {pad_v}px {pad_h}px;
            border-radius: {br}px;
            font-size: {fs}px;
            font-family: {FONT_FAMILY};
        }}
        QPushButton:hover {{
            background-color: {SELECTED_BG};
            border-color: {PRIMARY_DARK};
        }}
        QPushButton:pressed {{
            background-color: {BORDER};
        }}
    """


def action_button_style(primary=True):
    """Action button inside content pages."""
    s = _s()
    pad_v = s.dimension(8)
    pad_h = s.dimension(16)
    br = radius_sm()
    fs = s.font_size(13)
    if primary:
        return f"""
            QPushButton {{
                background-color: {PRIMARY};
                color: white;
                border: none;
                border-radius: {br}px;
                padding: {pad_v}px {pad_h}px;
                font-size: {fs}px;
                font-weight: 500;
                font-family: {FONT_FAMILY};
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {PRIMARY_DARK};
            }}
            QPushButton:pressed {{
                background-color: {PRIMARY_DARKER};
            }}
            QPushButton:disabled {{
                background-color: #B0BEC5;
            }}
        """
    else:
        return f"""
            QPushButton {{
                background-color: {BG_PRIMARY};
                color: {PRIMARY};
                border: 1px solid {BORDER};
                border-radius: {br}px;
                padding: {pad_v}px {pad_h}px;
                font-size: {fs}px;
                font-family: {FONT_FAMILY};
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {HOVER};
                border-color: {BORDER_DARK};
            }}
            QPushButton:pressed {{
                background-color: {BORDER};
            }}
        """


def group_box_style():
    """FeatureGroup (QGroupBox) stylesheet."""
    s = _s()
    fs = font_lg()
    br = radius_lg()
    mt = s.dimension(12)
    pt = s.dimension(16)
    tl = s.dimension(15)
    tp = s.dimension(5)
    return f"""
        QGroupBox {{
            font-size: {fs}px;
            font-weight: bold;
            font-family: {FONT_FAMILY};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER};
            border-radius: {br}px;
            margin-top: {mt}px;
            padding-top: {pt}px;
            background-color: {BG_CARD};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: {tl}px;
            padding: 0 {tp}px;
        }}
    """


def template_button_style():
    """Orange 'Setup Mapping Template' button at sidebar bottom."""
    s = _s()
    pad_v = s.dimension(10)
    pad_h = s.dimension(12)
    br = radius_md()
    margin = s.dimension(8)
    fs = font_md()
    return f"""
        QPushButton {{
            text-align: center;
            background-color: {ACCENT};
            border: 2px solid {ACCENT_PRESSED};
            padding: {pad_v}px {pad_h}px;
            border-radius: {br}px;
            color: white;
            font-weight: bold;
            font-size: {fs}px;
            font-family: {FONT_FAMILY};
            margin: {margin}px;
        }}
        QPushButton:hover {{
            background-color: {ACCENT_HOVER};
            border: 2px solid {ACCENT};
        }}
        QPushButton:pressed {{
            background-color: {ACCENT_PRESSED};
        }}
    """


def qfield_button_style():
    """Slate-blue 'Export for QField' button at sidebar bottom (above template)."""
    s = _s()
    pad_v = s.dimension(10)
    pad_h = s.dimension(12)
    br = radius_md()
    margin = s.dimension(8)
    fs = font_md()
    return f"""
        QPushButton {{
            text-align: center;
            background-color: {QFIELD};
            border: 2px solid {QFIELD_PRESSED};
            padding: {pad_v}px {pad_h}px;
            border-radius: {br}px;
            color: white;
            font-weight: bold;
            font-size: {fs}px;
            font-family: {FONT_FAMILY};
            margin: {margin}px;
        }}
        QPushButton:hover {{
            background-color: {QFIELD_HOVER};
            border: 2px solid {QFIELD};
        }}
        QPushButton:pressed {{
            background-color: {QFIELD_PRESSED};
        }}
    """


def reconcile_button_style():
    """Brand-green 'Reconcile / Merge' button at sidebar bottom (below QField export)."""
    s = _s()
    pad_v = s.dimension(10)
    pad_h = s.dimension(12)
    br = radius_md()
    margin = s.dimension(8)
    fs = font_md()
    return f"""
        QPushButton {{
            text-align: center;
            background-color: {RECONCILE};
            border: 2px solid {RECONCILE_PRESSED};
            padding: {pad_v}px {pad_h}px;
            border-radius: {br}px;
            color: white;
            font-weight: bold;
            font-size: {fs}px;
            font-family: {FONT_FAMILY};
            margin: {margin}px;
        }}
        QPushButton:hover {{
            background-color: {RECONCILE_HOVER};
            border: 2px solid {RECONCILE};
        }}
        QPushButton:pressed {{
            background-color: {RECONCILE_PRESSED};
        }}
    """


def separator_style():
    """Thin horizontal separator."""
    return f"background-color: {BORDER}; max-height: 1px;"


def section_label_style():
    """Section labels ('Quick Access', 'Navigation')."""
    s = _s()
    fs = font_sm()
    pad_v = s.dimension(2)
    pad_h = s.dimension(10)
    return f"font-weight: bold; color: {TEXT_SECONDARY}; font-size: {fs}px; font-family: {FONT_FAMILY}; padding: {pad_v}px {pad_h}px;"


def version_label_style():
    """Version info label at sidebar bottom."""
    s = _s()
    fs = font_xs()
    pad = s.dimension(4)
    mt = s.dimension(8)
    ml = s.dimension(8)
    return f"color: {TEXT_SECONDARY}; font-size: {fs}px; font-family: {FONT_FAMILY}; padding: {pad}px; margin-top: {mt}px; margin-left: {ml}px;"


def scrollbar_style():
    """Custom scrollbar appearance for sidebar scroll area."""
    s = _s()
    w = s.dimension(6)
    br = s.dimension(3)
    return f"""
        QScrollBar:vertical {{
            background: transparent;
            width: {w}px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {BORDER};
            min-height: {s.dimension(20)}px;
            border-radius: {br}px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {BORDER_DARK};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """


def dialog_style():
    """Top-level dialog stylesheet."""
    fs = font_lg()
    return f"""
        QDialog {{
            background-color: {BG_PRIMARY};
        }}
        QLabel {{
            font-size: {fs}px;
            font-family: {FONT_FAMILY};
            color: {TEXT_PRIMARY};
        }}
        QScrollArea {{
            border: none;
            background-color: transparent;
        }}
    """


def sidebar_style():
    """Sidebar scroll area wrapper."""
    return f"background-color: {BG_SIDEBAR}; border-right: 1px solid {BORDER};"


def content_area_style():
    """Content area background."""
    return f"background-color: {BG_PRIMARY};"


def page_header_style():
    """Page title label shown at top of content area."""
    fs = font_xl()
    return f"font-size: {fs}px; font-weight: bold; font-family: {FONT_FAMILY}; color: {TEXT_PRIMARY}; padding: 0;"


def info_dialog_style():
    """Info dialog (More Info) stylesheet."""
    fs = font_lg()
    br = radius_lg()
    return f"""
        QDialog {{
            background-color: {BG_CARD};
            border-radius: {br}px;
        }}
        QLabel {{
            font-size: {fs}px;
            line-height: 1.5;
            font-family: {FONT_FAMILY};
            color: {TEXT_PRIMARY};
        }}
        QScrollArea {{
            border: none;
            background-color: transparent;
        }}
    """


def header_title_style():
    """Brand header title label."""
    s = _s()
    fs = font_title()
    shadow = max(1, s.dimension(1))
    return f"""
        color: white;
        font-size: {fs}px;
        font-weight: bold;
        font-family: {FONT_FAMILY};
        letter-spacing: 0.5px;
        text-shadow: {shadow}px {shadow}px 3px rgba(0,0,0,0.3);
    """


def header_bottom_shadow():
    """CSS-like bottom border to give header depth (applied to a thin QFrame)."""
    return "background-color: rgba(0,0,0,0.12); max-height: 2px;"
