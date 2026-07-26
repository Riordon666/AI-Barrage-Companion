"""Custom-painted button family for the control panel.

Everything here is vector-drawn: no emoji glyphs, no QSS state snapping.
Hover and press are animated with the same gated-timer pattern the stat
cards use — a 16ms timer that only runs while something is actually moving,
so idle buttons cost nothing.

Variants
--------
primary   solid violet gradient, white text — the one main action on a page
ghost     hairline outline on a whisper of fill — secondary actions
danger    like flat, but warms to red — destructive actions
flat      invisible until hovered — chrome buttons (menu, quit)
nav       left-aligned icon + label for the sidebar, colors follow checked
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QAbstractButton, QWidget

from app.ui import theme
from app.ui.theme import PALETTE as _C


def _button_font(pixel_size: int = 13, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    return font


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


# ─── Vector icons ───────────────────────────────────────────────────────
#
# Each drawer paints into a 16×16 box whose top-left is (0, 0); the caller
# translates the painter and sets the pen colour. Stroke-only, round caps.

def _pen(color: QColor, width: float = 1.7) -> QPen:
    return QPen(
        color, width,
        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
    )


def _draw_menu(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    for y in (3.5, 8.0, 12.5):
        p.drawLine(QPointF(2.5, y), QPointF(13.5, y))


def _draw_home(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    path = QPainterPath(QPointF(2.5, 7.5))
    path.lineTo(8.0, 2.5)
    path.lineTo(13.5, 7.5)
    p.drawPath(path)
    body = QPainterPath(QPointF(4.0, 7.0))
    body.lineTo(4.0, 13.5)
    body.lineTo(12.0, 13.5)
    body.lineTo(12.0, 7.0)
    p.drawPath(body)
    p.drawLine(QPointF(6.8, 13.5), QPointF(6.8, 10.0))
    p.drawLine(QPointF(6.8, 10.0), QPointF(9.2, 10.0))
    p.drawLine(QPointF(9.2, 10.0), QPointF(9.2, 13.5))


def _draw_api(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(4.2, 11.8), 2.6, 2.6)
    p.drawEllipse(QPointF(11.8, 4.2), 2.6, 2.6)
    p.drawLine(QPointF(6.1, 9.9), QPointF(9.9, 6.1))


def _draw_sliders(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    rows = ((3.5, 10.5), (8.0, 5.5), (12.5, 9.5))
    for y, knob_x in rows:
        p.drawLine(QPointF(2.5, y), QPointF(13.5, y))
        p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(knob_x, y), 1.9, 1.9)
        p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_logs(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    for y in (4.0, 8.0, 12.0):
        p.drawLine(QPointF(5.5, y), QPointF(13.5, y))
        p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(2.8, y), 1.1, 1.1)
        p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_info(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(8.0, 8.0), 5.5, 5.5)
    p.drawLine(QPointF(8.0, 7.2), QPointF(8.0, 11.0))
    p.setBrush(QBrush(c))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(8.0, 4.9), 1.0, 1.0)


def _draw_pause(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.2))
    p.drawLine(QPointF(5.5, 3.5), QPointF(5.5, 12.5))
    p.drawLine(QPointF(10.5, 3.5), QPointF(10.5, 12.5))


def _draw_play(p: QPainter, c: QColor) -> None:
    path = QPainterPath(QPointF(5.0, 3.2))
    path.lineTo(13.0, 8.0)
    path.lineTo(5.0, 12.8)
    path.closeSubpath()
    p.setPen(_pen(c, 1.4))
    p.setBrush(QBrush(c))
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_x(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c))
    p.drawLine(QPointF(4.0, 4.0), QPointF(12.0, 12.0))
    p.drawLine(QPointF(12.0, 4.0), QPointF(4.0, 12.0))


def _draw_trash(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.5))
    p.drawLine(QPointF(3.0, 4.5), QPointF(13.0, 4.5))
    p.drawLine(QPointF(6.2, 4.2), QPointF(6.2, 2.8))
    p.drawLine(QPointF(6.2, 2.8), QPointF(9.8, 2.8))
    p.drawLine(QPointF(9.8, 2.8), QPointF(9.8, 4.2))
    body = QPainterPath(QPointF(4.4, 6.2))
    body.lineTo(5.0, 13.2)
    body.lineTo(11.0, 13.2)
    body.lineTo(11.6, 6.2)
    p.drawPath(body)
    p.drawLine(QPointF(7.0, 8.0), QPointF(7.2, 11.5))
    p.drawLine(QPointF(9.0, 8.0), QPointF(8.8, 11.5))


def _draw_bolt(p: QPainter, c: QColor) -> None:
    path = QPainterPath(QPointF(9.0, 2.5))
    path.lineTo(4.5, 9.0)
    path.lineTo(7.6, 9.0)
    path.lineTo(7.0, 13.5)
    path.lineTo(11.5, 7.0)
    path.lineTo(8.4, 7.0)
    path.closeSubpath()
    p.setPen(_pen(c, 1.3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _draw_check(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 2.0))
    path = QPainterPath(QPointF(3.2, 8.6))
    path.lineTo(6.6, 11.8)
    path.lineTo(12.8, 4.4)
    p.drawPath(path)


def _draw_arrow_r(p: QPainter, c: QColor) -> None:
    p.setPen(_pen(c, 1.8))
    path = QPainterPath(QPointF(6.0, 3.5))
    path.lineTo(10.5, 8.0)
    path.lineTo(6.0, 12.5)
    p.drawPath(path)


ICONS = {
    "menu": _draw_menu,
    "home": _draw_home,
    "api": _draw_api,
    "sliders": _draw_sliders,
    "logs": _draw_logs,
    "info": _draw_info,
    "pause": _draw_pause,
    "play": _draw_play,
    "x": _draw_x,
    "trash": _draw_trash,
    "bolt": _draw_bolt,
    "check": _draw_check,
    "arrow_r": _draw_arrow_r,
}

_ICON_BOX = 16.0


# ─── AnimatedButton ─────────────────────────────────────────────────────

class AnimatedButton(QAbstractButton):
    """Vector-icon button with animated hover/press states."""

    def __init__(
        self,
        text: str = "",
        icon: str | None = None,
        variant: str = "ghost",
        *,
        small: bool = False,
        checkable: bool = False,
        warm_checked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setText(text)
        self._icon = icon
        self._variant = variant
        self._small = small
        self._warm_checked = warm_checked
        self._hover = 0.0
        self._press = 0.0
        self._hover_t = 0.0
        self._press_t = 0.0

        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(28 if small else 34)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

        if checkable:
            self.toggled.connect(lambda _c: self.update())

    # -- public knobs ----------------------------------------------------

    def set_icon(self, name: str | None) -> None:
        if name != self._icon:
            self._icon = name
            self.updateGeometry()
            self.update()

    def set_variant(self, variant: str) -> None:
        if variant != self._variant:
            self._variant = variant
            self.update()

    def variant(self) -> str:
        return self._variant

    # -- geometry --------------------------------------------------------

    def sizeHint(self) -> QSize:  # type: ignore[override]
        metrics = QFontMetricsF(_button_font(12 if self._small else 13))
        width = metrics.horizontalAdvance(self.text()) if self.text() else 0.0
        pad = 14 if self._small else 18
        if self._icon:
            width += _ICON_BOX + (7 if self.text() else 0)
        return QSize(int(width + pad * 2), self.height())

    # -- animation plumbing ---------------------------------------------

    def _wake(self) -> None:
        if not self.isVisible():
            self._hover = self._hover_t
            self._press = self._press_t
            return
        if not self._timer.isActive():
            self._timer.start(16)

    def _tick(self) -> None:
        busy = False
        for attr, target in (("_hover", self._hover_t), ("_press", self._press_t)):
            value = getattr(self, attr)
            delta = target - value
            if abs(delta) > 0.02:
                setattr(self, attr, value + delta * 0.28)
                busy = True
            else:
                setattr(self, attr, target)
        self.update()
        if not busy:
            self._timer.stop()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hover_t = 1.0
        self._wake()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_t = 0.0
        self._press_t = 0.0
        self._wake()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._press_t = 1.0
        self._wake()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._press_t = 0.0
        self._wake()
        super().mouseReleaseEvent(event)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._timer.stop()
        self._hover = self._hover_t = 0.0
        self._press = self._press_t = 0.0
        super().hideEvent(event)

    # -- painting --------------------------------------------------------

    def _colors(self) -> tuple[QBrush | None, QColor | None, QColor]:
        """Return (fill, border, content) for the current state."""
        hover, press = self._hover, self._press
        checked = self.isCheckable() and self.isChecked()

        if self._variant == "primary":
            top = _mix(QColor(_C["accent"]), QColor("#ffffff"), 0.10 * hover)
            bottom = _mix(QColor(_C["accent_dk"]), QColor("#000000"), 0.12 * press)
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, bottom)
            return QBrush(gradient), None, QColor("#ffffff")

        if self._variant == "success":
            return QBrush(QColor(_C["green"])), None, QColor("#ffffff")

        if self._variant == "error":
            return QBrush(QColor(_C["red"])), None, QColor("#ffffff")

        if checked and self._warm_checked:
            fill = theme.accent2(int(52 + 26 * hover))
            border = theme.accent2(190)
            return QBrush(fill), border, QColor("#6b5d00")

        if self._variant == "ghost":
            fill = theme.accent(int(14 + 18 * hover + 14 * press))
            border = theme.accent(int(52 + 70 * hover))
            content = _mix(QColor(_C["text2"]), QColor(_C["text"]), hover)
            return QBrush(fill), border, content

        if self._variant == "danger":
            fill = QColor(239, 68, 68, int(26 * hover + 16 * press))
            border = QColor(239, 68, 68, int(90 * hover))
            content = _mix(QColor(_C["text3"]), QColor(_C["red"]), hover)
            return QBrush(fill) if fill.alpha() else None, border if border.alpha() else None, content

        if self._variant == "nav":
            fill = theme.accent(int(12 * hover))
            content = _mix(
                QColor(_C["text3"]) if not checked else QColor(_C["accent_dk"]),
                QColor(_C["text2"]) if not checked else QColor(_C["accent_dk"]),
                hover,
            )
            return (QBrush(fill) if fill.alpha() and not checked else None), None, content

        # flat
        fill = theme.accent(int(20 * hover + 14 * press))
        content = _mix(QColor(_C["text3"]), QColor(_C["text"]), hover)
        return QBrush(fill) if fill.alpha() else None, None, content

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        lift = -1.0 * self._hover + 1.4 * self._press
        if self._variant == "nav":
            lift = 0.0
        rect = QRectF(0.5, 0.5 + lift, self.width() - 1.0, self.height() - 1.0)
        radius = rect.height() / 2 if self._variant != "nav" else 12.0

        fill, border, content = self._colors()
        if not self.isEnabled():
            content = QColor(_C["text3"])
            content.setAlpha(150)

        if fill is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(rect, radius, radius)
        if border is not None:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(border, 1))
            p.drawRoundedRect(rect, radius, radius)

        # Content layout: centered icon+text group, or left-aligned for nav.
        font = _button_font(12 if self._small else 13)
        metrics = QFontMetricsF(font)
        text = self.text()
        text_w = metrics.horizontalAdvance(text) if text else 0.0
        icon_w = _ICON_BOX if self._icon else 0.0
        gap = 7.0 if (self._icon and text) else 0.0
        group_w = icon_w + gap + text_w

        if self._variant == "nav" and text:
            x = 16.0
        else:
            x = (self.width() - group_w) / 2

        y_mid = rect.center().y()
        if self._icon:
            drawer = ICONS.get(self._icon)
            if drawer is not None:
                p.save()
                p.translate(x, y_mid - _ICON_BOX / 2)
                drawer(p, content)
                p.restore()
            x += icon_w + gap

        if text:
            p.setPen(content)
            p.setFont(font)
            p.drawText(
                QRectF(x, rect.top(), max(1.0, self.width() - x), rect.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
        p.end()


# ─── SegmentedTabs ──────────────────────────────────────────────────────

class SegmentedTabs(QWidget):
    """Pill-shaped tab strip with a sliding thumb under the active label."""

    currentChanged = Signal(int)

    def __init__(self, labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels = labels
        self._index = 0
        self._thumb = 0.0  # animated, in units of segment index
        self._hover_seg = -1
        self._seg_w = 64
        self.setFixedSize(self._seg_w * len(labels) + 8, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    def currentIndex(self) -> int:
        return self._index

    def setCurrentIndex(self, index: int) -> None:
        index = max(0, min(len(self._labels) - 1, index))
        if index == self._index:
            return
        self._index = index
        if self.isVisible():
            if not self._timer.isActive():
                self._timer.start(16)
        else:
            self._thumb = float(index)
        self.currentChanged.emit(index)
        self.update()

    def _tick(self) -> None:
        delta = self._index - self._thumb
        if abs(delta) < 0.01:
            self._thumb = float(self._index)
            self._timer.stop()
        else:
            self._thumb += delta * 0.25
        self.update()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._timer.stop()
        self._thumb = float(self._index)
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.setCurrentIndex(int((event.position().x() - 4) // self._seg_w))

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        seg = int((event.position().x() - 4) // self._seg_w)
        seg = max(0, min(len(self._labels) - 1, seg))
        if seg != self._hover_seg:
            self._hover_seg = seg
            self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_seg = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Track
        track = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.accent(16))
        p.drawRoundedRect(track, h / 2, h / 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.accent(36), 1))
        p.drawRoundedRect(track, h / 2, h / 2)

        # Thumb
        thumb_x = 4 + self._thumb * self._seg_w
        thumb = QRectF(thumb_x, 3.5, self._seg_w, h - 7.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(thumb, thumb.height() / 2, thumb.height() / 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.accent(70), 1))
        p.drawRoundedRect(thumb, thumb.height() / 2, thumb.height() / 2)

        # Labels
        font = _button_font(12)
        p.setFont(font)
        for i, label in enumerate(self._labels):
            cell = QRectF(4 + i * self._seg_w, 0, self._seg_w, h)
            if i == self._index:
                color = QColor(_C["accent_dk"])
            elif i == self._hover_seg:
                color = QColor(_C["text2"])
            else:
                color = QColor(_C["text3"])
            p.setPen(color)
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, label)
        p.end()
