"""Design tokens for the ABC desktop UI.

Everything visual — colours, radii, elevation, motion timing — is declared
here so the control panel and the overlay stay in sync.  ``PALETTE`` keeps the
key names the control panel already uses, so call sites read ``_C['accent']``
unchanged.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# ─── Colour ─────────────────────────────────────────────────────────────

PALETTE: dict[str, str] = {
    # Surfaces: the page sits on a faintly tinted ground so white cards read
    # as lifted rather than flush.
    "bg":         "#fcfbff",
    "bg2":        "#f7f5fd",
    "card":       "#ffffff",
    "surface":    "rgba(159,130,253,0.055)",
    "surface2":   "rgba(159,130,253,0.115)",
    "surface_y":  "rgba(251,234,3,0.08)",
    "surface_y2": "rgba(251,234,3,0.12)",
    # Borders
    "border":     "rgba(159,130,253,0.16)",
    "border_l":   "rgba(159,130,253,0.30)",
    "border_y":   "rgba(251,234,3,0.20)",
    "highlight":  "rgba(255,255,255,0.85)",
    # Text
    "text":       "#191428",
    "text2":      "#585070",
    "text3":      "#9a94ad",
    # Brand
    "accent":     "#9F82FD",
    "accent_dk":  "#7B5CF0",
    "accent2":    "#FBEA03",
    # Semantic
    "green":      "#16a34a",
    "red":        "#ef4444",
    "cyan":       "#06b6d4",
}

# Brand colours as RGB triples, for painters that build QColor with alpha.
ACCENT_RGB = (159, 130, 253)
ACCENT2_RGB = (251, 234, 3)
SHADOW_RGB = (86, 58, 168)  # violet-tinted shadow, far softer than pure black


def rgba(rgb: tuple[int, int, int], alpha: int) -> QColor:
    """Build a QColor from an RGB triple plus an 0–255 alpha."""
    return QColor(rgb[0], rgb[1], rgb[2], alpha)


def accent(alpha: int = 255) -> QColor:
    return rgba(ACCENT_RGB, alpha)


def accent2(alpha: int = 255) -> QColor:
    return rgba(ACCENT2_RGB, alpha)


def ink(key: str) -> QColor:
    """QColor for a named palette entry."""
    return QColor(PALETTE[key])


# ─── Geometry ───────────────────────────────────────────────────────────

RADIUS_SM = 8
RADIUS_MD = 12
RADIUS_LG = 16
RADIUS_XL = 20

SIDEBAR_W = 216
SIDEBAR_COLLAPSED_W = 64


# ─── Elevation ──────────────────────────────────────────────────────────

# (blur radius, y offset, alpha) per elevation level.
_ELEVATION = {
    1: (18, 3, 26),
    2: (30, 6, 34),
    3: (48, 12, 42),
}


def shadow(widget: QWidget, level: int = 2) -> QGraphicsDropShadowEffect:
    """Attach a violet-tinted drop shadow. Higher *level* floats further."""
    blur, offset_y, alpha = _ELEVATION.get(level, _ELEVATION[2])
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setColor(rgba(SHADOW_RGB, alpha))
    effect.setOffset(0, offset_y)
    widget.setGraphicsEffect(effect)
    return effect


# ─── Motion ─────────────────────────────────────────────────────────────

DUR_FAST = 140
DUR_BASE = 220
DUR_SLOW = 320

# Decelerating curve for anything entering or settling; the standard choice
# for UI that should feel responsive on press and calm on release.
EASE_OUT = QEasingCurve.Type.OutCubic
EASE_IN_OUT = QEasingCurve.Type.InOutCubic
# Slight overshoot, for the nav indicator only — used sparingly.
EASE_SPRING = QEasingCurve.Type.OutBack


# ─── Shared stylesheets ─────────────────────────────────────────────────

_C = PALETTE  # local alias to keep the f-strings below readable

COMBO_STYLE = f"""
    QComboBox {{
        background: rgba(159,130,253,0.06);
        color: {_C['text']};
        border: 1px solid {_C['border']};
        border-radius: {RADIUS_SM}px;
        padding: 6px 12px;
        font-size: 13px;
        min-width: 120px;
    }}
    QComboBox:hover {{ border-color: {_C['border_l']}; background: rgba(159,130,253,0.10); }}
    QComboBox:focus {{ border-color: {_C['accent']}; }}
    QComboBox::drop-down {{ border: none; padding-right: 8px; }}
    QComboBox::down-arrow {{ image: none; }}
    QComboBox QAbstractItemView {{
        background: #ffffff;
        color: {_C['text']};
        border: 1px solid {_C['border']};
        border-radius: {RADIUS_SM}px;
        padding: 4px;
        selection-background-color: rgba(159,130,253,0.15);
        outline: none;
    }}
"""

LINE_EDIT_STYLE = f"""
    QLineEdit {{
        background: rgba(159,130,253,0.06);
        color: {_C['text']};
        border: 1px solid {_C['border']};
        border-radius: {RADIUS_SM}px;
        padding: 7px 12px;
        font-size: 13px;
    }}
    QLineEdit:hover {{ border-color: {_C['border_l']}; }}
    QLineEdit:focus {{ border-color: {_C['accent']}; background: rgba(159,130,253,0.03); }}
"""

PRIMARY_BUTTON_STYLE = f"""
    QPushButton {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {_C['accent']}, stop:1 {_C['accent2']});
        color: #191428;
        border: none;
        border-radius: {RADIUS_MD}px;
        padding: 0 20px;
        font-size: 13px;
        font-weight: 700;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 {_C['accent_dk']}, stop:1 {_C['accent2']});
    }}
    QPushButton:pressed {{ padding-top: 1px; }}
"""

GHOST_BUTTON_STYLE = f"""
    QPushButton {{
        background: rgba(159,130,253,0.07);
        color: {_C['text']};
        border: 1px solid {_C['border']};
        border-radius: {RADIUS_MD}px;
        padding: 0 20px;
        font-size: 13px;
    }}
    QPushButton:hover {{ border-color: {_C['accent']}; background: rgba(159,130,253,0.13); }}
    QPushButton:pressed {{ background: rgba(159,130,253,0.18); }}
    QPushButton:disabled {{ color: {_C['text3']}; border-color: {_C['border']}; }}
"""

SLIDER_STYLE = f"""
    QSlider {{ background: transparent; border: none; }}
    QSlider::groove:horizontal {{
        background: rgba(159,130,253,0.12);
        height: 6px;
        border-radius: 3px;
        border: none;
    }}
    QSlider::handle:horizontal {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #ffffff, stop:1 {_C['accent2']});
        border: 1px solid rgba(159,130,253,0.45);
        width: 16px;
        height: 16px;
        margin: -6px 0;
        border-radius: 9px;
    }}
    QSlider::handle:horizontal:hover {{ border-color: {_C['accent']}; }}
    QSlider::handle:horizontal:pressed {{
        background: {_C['accent']};
        border-color: {_C['accent_dk']};
    }}
    QSlider::sub-page:horizontal {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 {_C['accent']}, stop:1 {_C['accent2']});
        border-radius: 3px;
    }}
"""
