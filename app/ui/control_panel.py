"""Control panel UI — sidebar navigation, live stats, settings and logs."""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import (
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config.provider_presets import SUPPORTED_PROVIDERS, provider_for_key
from app.core.logger import get_emitter, get_logger
from app.core.utils import as_density
from app.models import ApiConfig, AppSettings
from app.ui import theme
from app.ui.buttons import AnimatedButton, SegmentedTabs
from app.ui.motion import SnapshotFader, animate, animate_geometry, stop_safely
from app.ui.theme import (
    COMBO_STYLE as _COMBO_STYLE,
    DUR_BASE,
    DUR_SLOW,
    EASE_OUT,
    LINE_EDIT_STYLE,
    PALETTE as _C,
    SIDEBAR_COLLAPSED_W as _SIDEBAR_COLLAPSED_W,
    SIDEBAR_W as _SIDEBAR_W,
    SLIDER_STYLE,
)

logger = get_logger("control_panel")

_shadow = theme.shadow


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _paint_card(
    painter: QPainter,
    rect: QRectF,
    radius: float,
    *,
    tint: tuple[int, int, int] = theme.ACCENT_RGB,
    fill_alpha: int = 18,
    border_alpha: int = 45,
) -> QPainterPath:
    """Paint the shared card treatment: soft tinted body, hairline border and
    a top inner highlight that reads as light falling from above."""
    path = _rounded(rect, radius)

    body = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    body.setColorAt(0.0, theme.rgba(tint, max(0, fill_alpha - 6)))
    body.setColorAt(1.0, theme.rgba(tint, fill_alpha + 6))
    painter.fillPath(path, QBrush(body))

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(theme.rgba(tint, border_alpha), 1))
    painter.drawPath(path)

    # 1px highlight hugging the top edge only.
    highlight = QPainterPath()
    highlight.addRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
    painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
    painter.setClipRect(QRectF(rect.left(), rect.top(), rect.width(), radius))
    painter.drawPath(highlight)
    painter.setClipping(False)
    return path


# ─── Glow Dot ──────────────────────────────────────────────────────────

class GlowDot(QWidget):
    """Status dot with a slow breathing halo.

    The pulse timer only runs while the dot is actually on screen — three of
    these live in the chrome, and the panel spends most of its life minimised
    to the tray.
    """

    def __init__(self, color: str = _C["green"], size: int = 10, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size + 10, size + 10)
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_color(self, color: str) -> None:
        new = QColor(color)
        if new == self._color:
            return
        self._color = new
        self.update()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(33)  # 30fps is ample for a 2s breath cycle

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.10) % (2 * math.pi)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = self._size / 2
        breath = 0.5 + 0.5 * math.sin(self._pulse)

        glow = QRadialGradient(cx, cy, r * 2.6)
        c = QColor(self._color)
        c.setAlpha(int(26 + 30 * breath))
        glow.setColorAt(0.35, c)
        c.setAlpha(0)
        glow.setColorAt(1, c)
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r * 2.6, r * 2.6)

        # Core dot with a light top edge so it reads as a bead, not a blob.
        bead = QLinearGradient(cx, cy - r, cx, cy + r)
        bead.setColorAt(0.0, self._color.lighter(128))
        bead.setColorAt(1.0, self._color)
        p.setBrush(QBrush(bead))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# ─── Stat Card (custom painted) ────────────────────────────────────────

def _parse_int(text: str) -> int | None:
    """Return the value as an int, or None when it isn't a plain integer."""
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class StatCard(QFrame):
    """Metric tile that counts up to new values and lifts on hover.

    A single timer serves the hover lerp, the count-up and the change flash,
    and it stops as soon as all three have settled — eight of these sit on the
    home page, so an always-on timer per card would be pure idle burn.
    """

    def __init__(self, title: str, value: str = "0", color: str = _C["accent"],
                 icon: str = "", yellow: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        self._icon = icon
        self._yellow = yellow
        self._tint = theme.ACCENT2_RGB if yellow else theme.ACCENT_RGB
        self._text_value = value
        self._numeric = _parse_int(value)
        self._shown = float(self._numeric or 0)
        self._hover = 0.0
        self._hover_target = 0.0
        self._flash = 0.0
        self._fit_key: tuple[str, int] | None = None
        self._fit_size = 20
        self.setFixedHeight(96)
        self.setMinimumWidth(110)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # -- state ----------------------------------------------------------

    def set_value(self, value: str) -> None:
        if value == self._text_value:
            return
        self._text_value = value
        parsed = _parse_int(value)
        if parsed is not None and self._numeric is None:
            self._shown = float(parsed)  # first numeric reading: don't ramp
        self._numeric = parsed
        self._flash = 1.0
        self._wake()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hover_target = 1.0
        self._wake()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_target = 0.0
        self._wake()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._timer.stop()
        self._settle()
        super().hideEvent(event)

    def _settle(self) -> None:
        if self._numeric is not None:
            self._shown = float(self._numeric)
        self._hover = self._hover_target
        self._flash = 0.0

    def _wake(self) -> None:
        if not self.isVisible():
            self._settle()
            return
        if not self._timer.isActive():
            self._timer.start(16)

    def _tick(self) -> None:
        busy = False

        delta = self._hover_target - self._hover
        if abs(delta) > 0.004:
            self._hover += delta * 0.22
            busy = True
        else:
            self._hover = self._hover_target

        if self._numeric is not None:
            delta = self._numeric - self._shown
            if abs(delta) > 0.5:
                self._shown += delta * 0.20
                busy = True
            else:
                self._shown = float(self._numeric)

        if self._flash > 0.001:
            self._flash = max(0.0, self._flash - 0.055)
            busy = True

        self.update()
        if not busy:
            self._timer.stop()

    # -- paint ----------------------------------------------------------

    def _fitted_size(self, value: str, width: int) -> int:
        """Largest point size at which *value* still fits the card.

        Long readings such as an uptime of "3h 42m 17s" would otherwise spill
        past the rounded edge. Memoised because paintEvent runs at 60fps while
        a value is counting up.
        """
        key = (value, width)
        if key == self._fit_key:
            return self._fit_size

        available = width - 20
        size = 20
        while size > 11:
            metrics = QFontMetricsF(QFont("Segoe UI", size, QFont.Weight.ExtraBold))
            if metrics.horizontalAdvance(value) <= available:
                break
            size -= 1

        self._fit_key = key
        self._fit_size = size
        return size

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Hovering floats the card up; the strip it vacates falls back to the
        # page background, which is what sells the lift.
        lift = 3.0 * self._hover
        rect = QRectF(0.5, 0.5 - lift, w - 1.0, h - 1.0)
        glow = self._hover + self._flash * 0.6

        _paint_card(
            p, rect, 14.0,
            tint=self._tint,
            fill_alpha=int(16 + 12 * glow),
            border_alpha=int(42 + 46 * glow),
        )

        # Title
        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(
            QRectF(0, rect.top() + 13, w, 18),
            Qt.AlignmentFlag.AlignCenter,
            self._title,
        )

        # Value — flashes toward the accent for a beat whenever it changes.
        value = (
            str(int(round(self._shown)))
            if self._numeric is not None
            else self._text_value
        )
        p.setPen(_mix(QColor(_C["text"]), QColor(_C["accent_dk"]), self._flash))
        p.setFont(QFont("Segoe UI", self._fitted_size(value, w), QFont.Weight.ExtraBold))
        p.drawText(
            QRectF(0, rect.top() + 33, w, 34),
            Qt.AlignmentFlag.AlignCenter,
            value,
        )

        # Underline that widens on hover.
        bar_w = 22.0 + 26.0 * self._hover
        bar = QRectF((w - bar_w) / 2, rect.bottom() - 9, bar_w, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.rgba(self._tint, int(70 + 110 * self._hover)))
        p.drawRoundedRect(bar, 1.5, 1.5)
        p.end()


# ─── API Status Card (expanded) ───────────────────────────────────────

class ApiStatusCard(QFrame):
    """Shows current API provider with detailed stats grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(148)
        self._provider = "未配置"
        self._model = ""
        self._url = ""
        self._online = False
        self._resp_time = "—"
        self._call_count = "0"
        self._success_rate = "—"
        self._conn_status = "未连接"
        self._state: tuple | None = None

    def set_info(self, provider: str, model: str, url: str, online: bool,
                 resp_time: str = "—", call_count: str = "0",
                 success_rate: str = "—") -> None:
        state = (provider, model, url, online, resp_time, call_count, success_rate)
        if state == self._state:
            return  # called once a second; skip the repaint when nothing moved
        self._state = state
        self._provider = provider
        self._model = model
        self._url = url
        self._online = online
        self._resp_time = resp_time
        self._call_count = call_count
        self._success_rate = success_rate
        self._conn_status = "正常" if online else "离线"
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        _paint_card(
            p, QRectF(0.5, 0.5, w - 1.0, h - 1.0), 16.0,
            tint=theme.ACCENT2_RGB, fill_alpha=22, border_alpha=58,
        )

        # Provider name, with the online badge tucked in right after it.
        name_text = f"{self._provider} · {self._model}" if self._model else self._provider
        name_text = name_text[:50]
        p.setPen(QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        p.drawText(QRectF(24, 20, w - 200, 24), Qt.AlignmentFlag.AlignLeft, name_text)

        if self._online:
            name_w = p.fontMetrics().horizontalAdvance(name_text)
            badge_x = 24 + min(name_w + 12, w - 250)
            badge = QRectF(badge_x, 23, 44, 19)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(22, 163, 74, 32))
            p.drawRoundedRect(badge, 9.5, 9.5)
            p.setPen(QColor(_C["green"]))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, "在线")

        # URL
        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Consolas", 10))
        p.drawText(QRectF(24, 52, w - 48, 16), Qt.AlignmentFlag.AlignLeft, self._url[:80])

        # Stats grid (4 columns)
        stats = [
            ("连接状态", self._conn_status, self._online),
            ("响应时间", self._resp_time, False),
            ("调用次数", self._call_count, False),
            ("成功率", self._success_rate, "%" in self._success_rate),
        ]
        col_w = (w - 72) / 4
        y_base = 84
        for i, (label, value, is_ok) in enumerate(stats):
            x = 24 + i * col_w
            cell = QRectF(x, y_base, col_w - 8, 44)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.accent(14))
            p.drawRoundedRect(cell, 8, 8)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(theme.accent(24), 1))
            p.drawRoundedRect(cell.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

            p.setPen(QColor(_C["text3"]))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(x + 4, y_base + 6, col_w - 16, 14), Qt.AlignmentFlag.AlignCenter, label)

            p.setPen(QColor(_C["green"]) if is_ok else QColor(_C["text"]))
            p.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            p.drawText(QRectF(x + 4, y_base + 22, col_w - 16, 18), Qt.AlignmentFlag.AlignCenter, value)

        p.end()


# ─── Greeting Banner ───────────────────────────────────────────────────

class GreetingBanner(QFrame):
    """Welcome banner with greeting text and live clock."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(92)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(1000)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        path = _rounded(rect, 16.0)

        # Brand wash: violet on the left drifting to yellow on the right.
        wash = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
        wash.setColorAt(0.0, theme.accent(34))
        wash.setColorAt(0.55, theme.accent(16))
        wash.setColorAt(1.0, theme.accent2(30))
        p.fillPath(path, QBrush(wash))

        # Bloom behind the clock so the numerals sit on their own pool of light.
        bloom = QRadialGradient(rect.right() - 90, rect.center().y(), 150)
        bloom.setColorAt(0.0, QColor(255, 255, 255, 130))
        bloom.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(bloom))

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.accent(58), 1))
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.setClipRect(QRectF(rect.left(), rect.top(), rect.width(), 16))
        p.drawPath(_rounded(rect.adjusted(1, 1, -1, -1), 15.0))
        p.setClipping(False)

        # Greeting
        hour = time.localtime().tm_hour
        if hour < 6:
            greet = "凌晨好"
        elif hour < 12:
            greet = "上午好"
        elif hour < 14:
            greet = "中午好"
        elif hour < 18:
            greet = "下午好"
        else:
            greet = "晚上好"

        p.setPen(QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        p.drawText(
            QRectF(24, 18, w - 220, 26),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"👋 {greet}！",
        )

        p.setPen(QColor(_C["text2"]))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(QRectF(24, 49, w - 220, 18), Qt.AlignmentFlag.AlignLeft, "今天又是弹幕陪伴的一天~")

        # Clock
        now = time.localtime()
        clock_text = time.strftime("%H:%M:%S", now)
        date_text = time.strftime(f"%Y-%m-%d 星期{'一二三四五六日'[now.tm_wday]}", now)

        p.setPen(QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 28, QFont.Weight.ExtraBold))
        clock_w = p.fontMetrics().horizontalAdvance(clock_text)
        clock_x = w - clock_w - 32
        p.drawText(
            QRectF(clock_x, 6, clock_w + 16, 42),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            clock_text,
        )

        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(
            QRectF(clock_x - 12, 50, clock_w + 28, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            date_text,
        )
        p.end()


# ─── Modern Toggle ─────────────────────────────────────────────────────

class ModernToggle(QCheckBox):
    """Switch with a knob that slides between states.

    Qt stylesheets can only swap the indicator's colour, which reads as a
    blinking rectangle; painting it here buys a real travelling knob for the
    cost of one short-lived timer per flip.
    """

    _TRACK_W = 44
    _TRACK_H = 22
    _GAP = 12

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QCheckBox{background:transparent;border:none;font-size:13px}")
        self._pos = 1.0 if self.isChecked() else 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self.toggled.connect(self._on_toggled)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        metrics = self.fontMetrics()
        text_w = metrics.horizontalAdvance(self.text())
        return QSize(
            self._TRACK_W + self._GAP + text_w + 4,
            max(self._TRACK_H + 6, metrics.height() + 8),
        )

    def hitButton(self, pos) -> bool:  # type: ignore[override]
        # The painted layout doesn't match QCheckBox's style-derived hit
        # region, so make the whole widget clickable.
        return self.rect().contains(pos)

    def _on_toggled(self, _checked: bool) -> None:
        if not self.isVisible():
            self._pos = 1.0 if self.isChecked() else 0.0
            self.update()
            return
        if not self._timer.isActive():
            self._timer.start(16)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._timer.stop()
        self._pos = 1.0 if self.isChecked() else 0.0
        super().hideEvent(event)

    def _tick(self) -> None:
        target = 1.0 if self.isChecked() else 0.0
        delta = target - self._pos
        if abs(delta) < 0.01:
            self._pos = target
            self._timer.stop()
        else:
            self._pos += delta * 0.28
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_y = (self.height() - self._TRACK_H) / 2
        track = QRectF(1, track_y, self._TRACK_W, self._TRACK_H)
        radius = self._TRACK_H / 2

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_mix(QColor(224, 217, 249), QColor(_C["accent2"]), self._pos))
        p.drawRoundedRect(track, radius, radius)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_mix(theme.accent(70), theme.accent2(150), self._pos), 1))
        p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        # Knob
        knob_d = self._TRACK_H - 6
        travel = self._TRACK_W - knob_d - 6
        knob_x = track.left() + 3 + travel * self._pos
        knob = QRectF(knob_x, track_y + 3, knob_d, knob_d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.rgba(theme.SHADOW_RGB, 46))
        p.drawEllipse(knob.translated(0, 1))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(knob)

        # Label
        p.setPen(QColor(_C["text2"] if self.isEnabled() else _C["text3"]))
        p.setFont(self.font())
        text_x = self._TRACK_W + self._GAP
        p.drawText(
            QRectF(text_x, 0, max(0, self.width() - text_x), self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        p.end()


# ─── ComboBox (no scroll hijack) ─────────────────────────────────────────

class NoScrollComboBox(QComboBox):
    """QComboBox that ignores mouse wheel to prevent accidental value changes."""

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


# ─── Sliders ────────────────────────────────────────────────────────────

_STEP_SLIDER_STYLE = SLIDER_STYLE

_FONT_SIZE_LABELS = ["小", "较小", "适中", "较大", "大"]
_FONT_SIZE_PX = [14, 18, 24, 32, 42]
_DISPLAY_AREA_LABELS = ["20%", "40%", "60%", "80%", "100%"]
_DISPLAY_AREA_VALUES = [20, 40, 60, 80, 100]
_SPEED_LABELS = ["慢", "较慢", "适中", "较快", "快"]


class NoScrollSlider(QSlider):
    """QSlider that ignores mouse wheel to prevent accidental value changes."""

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class TickedSlider(QWidget):
    """Slider with discrete tick labels, for 5-level stepped settings."""

    valueChanged = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self._labels = labels
        self._n = len(labels)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._slider = NoScrollSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, self._n - 1)
        self._slider.setPageStep(1)
        self._slider.setStyleSheet(_STEP_SLIDER_STYLE)
        self._slider.valueChanged.connect(self._on_value)
        lay.addWidget(self._slider)

        self._val_label = QLabel(labels[0])
        self._val_label.setFixedWidth(64)
        self._val_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._val_label.setStyleSheet(f"color:{_C['text']};font-size:12px;font-weight:600;background:transparent;border:none")

    def _on_value(self, v: int) -> None:
        if 0 <= v < len(self._labels):
            self._val_label.setText(self._labels[v])
        self.valueChanged.emit(v)

    def setValue(self, v: int) -> None:
        self._slider.setValue(v)
        if 0 <= v < len(self._labels):
            self._val_label.setText(self._labels[v])

    def value(self) -> int:
        return self._slider.value()

    def value_label(self) -> QLabel:
        return self._val_label


# ─── Section Card ──────────────────────────────────────────────────────

class SectionCard(QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(22, 18, 22, 18)
        self._layout.setSpacing(12)
        # Solid white against the faintly tinted page: the separation comes
        # from elevation rather than from another wash of purple.
        self.setStyleSheet(f"""
            QFrame {{
                background: {_C['card']};
                border: 1px solid {_C['border']};
                border-radius: 16px;
            }}
        """)
        _shadow(self, level=1)
        if title:
            lbl = QLabel(title)
            lbl.setStyleSheet(f"color:{_C['text']};font-size:13px;font-weight:700;background:transparent;border:none;letter-spacing:0.4px")
            self._layout.addWidget(lbl)
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background:{_C['border']};border:none")
            self._layout.addWidget(sep)

    def add_row(self, label_text: str, widget: QWidget) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)
        lbl = QLabel(label_text)
        lbl.setFixedWidth(90)
        lbl.setStyleSheet(f"color:{_C['text2']};font-size:13px;background:transparent;border:none")
        row.addWidget(lbl)
        row.addWidget(widget, 1)
        self._layout.addLayout(row)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


# ─── Navigation ────────────────────────────────────────────────────────

class NavIndicator(QWidget):
    """The pill that slides behind whichever nav item is active.

    It sits underneath the buttons rather than being their background, so one
    animated widget carries the selection instead of five stylesheet swaps.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = _rounded(rect, 12.0)

        wash = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        wash.setColorAt(0.0, theme.accent(46))
        wash.setColorAt(1.0, theme.accent2(26))
        p.fillPath(path, QBrush(wash))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(theme.accent(64), 1))
        p.drawPath(path)

        # Accent bar on the leading edge.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_C["accent"]))
        p.drawRoundedRect(QRectF(rect.left() + 4, rect.center().y() - 9, 3, 18), 1.5, 1.5)
        p.end()


class NavArea(QWidget):
    """Nav button container that keeps *on_resize* informed.

    The indicator is positioned absolutely, so it has to be re-synced whenever
    the buttons are re-laid-out — on window resize and while the sidebar
    collapse animation is running.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_resize = None

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self.on_resize is not None:
            self.on_resize()


# ═══════════════════════════════════════════════════════════════════════
#  MAIN CONTROL PANEL
# ═══════════════════════════════════════════════════════════════════════

class ControlPanel(QWidget):
    pauseChanged = Signal(bool)
    densityChanged = Signal(str)
    displayAreaChanged = Signal(int)
    fontSizeChanged = Signal(int)
    opacityChanged = Signal(int)
    speedChanged = Signal(int)
    settingsSaved = Signal(AppSettings)
    quitRequested = Signal()

    _NAV = [
        ("首页",    "home"),
        ("API 配置", "api"),
        ("设置",    "sliders"),
        ("日志",    "logs"),
        ("关于",    "info"),
    ]

    _NAV_SUBTITLES = [
        "AI 弹幕陪伴 · 智能生成 · 实时互动",
        "配置 AI 模型提供商、API Key 与连接测试",
        "自定义弹幕行为、显示效果与 API 连接",
        "实时监控系统运行状态、OCR 识别结果与 API 调用记录",
        "关于 AI Barrage Companion",
    ]

    def __init__(self, settings: AppSettings, settings_store=None) -> None:
        super().__init__()
        self.setWindowTitle("AI Barrage Companion")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 750)
        self._settings = settings
        self._settings_store = settings_store
        self._controller = None
        self._sidebar_anims: list = []
        self._indicator_anim = None
        self._build()
        self._apply_global()
        self._load_settings(settings)
        self._connect_logger()
        self._activity_items: list[tuple[str, str, str, str]] = []

    # ── Build ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._mk_sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._mk_topbar())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_home())
        self._stack.addWidget(self._page_api())
        self._stack.addWidget(self._page_settings())
        self._stack.addWidget(self._page_logs())
        self._stack.addWidget(self._page_about())
        # Cross-fades page changes; see SnapshotFader for why it works on a
        # grabbed still rather than on the live pages.
        self._fader = SnapshotFader(self._stack)
        right.addWidget(self._stack, 1)
        right.addWidget(self._mk_bottombar())

        root.addLayout(right, 1)
        self._nav_area.on_resize = self._sync_indicator

    # ── Visibility: nothing animates while the panel is in the tray ──────

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        # Layouts have not necessarily settled yet during showEvent.
        QTimer.singleShot(0, self._sync_indicator)
        if self._controller is not None and not self._stats_timer.isActive():
            self._stats_timer.start()
        if not self._time_timer.isActive():
            self._time_timer.start(1000)
        self._tick_clock()
        # NOTE: no windowOpacity fade here. Animating opacity from inside
        # showEvent toggles WS_EX_LAYERED mid-show on Windows and the native
        # window can end up never becoming visible at all.

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._stats_timer.stop()
        self._time_timer.stop()
        super().hideEvent(event)

    # ── Sidebar (collapsible: 216px ↔ 64px) ─────────────────────────────

    def _mk_sidebar(self) -> QFrame:
        self._sidebar_collapsed = False

        sb = QFrame()
        sb.setFixedWidth(_SIDEBAR_W)
        sb.setObjectName("sidebar")
        sb.setStyleSheet(f"""
            QFrame#sidebar {{
                background: {_C['bg2']};
                border-right: 1px solid {_C['border']};
            }}
        """)
        self._sidebar = sb

        lay = QVBoxLayout(sb)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Logo area — gradient card
        logo_card = QFrame()
        logo_card.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {_C['accent']}, stop:1 {_C['accent2']});
                border-radius: 14px;
            }}
        """)
        _shadow(logo_card, level=2)
        logo_inner = QVBoxLayout(logo_card)
        logo_inner.setContentsMargins(18, 14, 18, 14)
        logo_inner.setSpacing(2)
        logo_cn = QLabel("AI 弹幕伴侣")
        logo_cn.setStyleSheet("color:#000;font-size:14px;font-weight:800;background:transparent;border:none")
        logo_inner.addWidget(logo_cn)
        logo_en = QLabel("AI BARRAGE COMPANION")
        logo_en.setStyleSheet("color:rgba(0,0,0,0.55);font-size:8px;font-weight:600;background:transparent;border:none;letter-spacing:0.8px")
        logo_inner.addWidget(logo_en)
        self._logo_card = logo_card

        logo_wrap = QHBoxLayout()
        logo_wrap.setContentsMargins(16, 20, 16, 8)
        logo_wrap.addWidget(logo_card, 1)
        lay.addLayout(logo_wrap)

        # Nav buttons. The indicator is created first so it stays behind them
        # in the sibling stacking order.
        nav_area = NavArea()
        nav_area.setStyleSheet("background:transparent;border:none")
        self._nav_area = nav_area
        self._nav_indicator = NavIndicator(nav_area)
        self._nav_indicator.hide()

        nav_lay = QVBoxLayout(nav_area)
        nav_lay.setContentsMargins(12, 20, 12, 0)
        nav_lay.setSpacing(4)

        self._nav_btns: list[AnimatedButton] = []
        for i, (name, icon) in enumerate(self._NAV):
            btn = AnimatedButton(name, icon=icon, variant="nav", checkable=True)
            btn.setFixedHeight(44)
            btn.clicked.connect(lambda _, idx=i: self._switch_page(idx))
            nav_lay.addWidget(btn)
            self._nav_btns.append(btn)
        self._nav_btns[0].setChecked(True)

        nav_lay.addStretch()
        lay.addWidget(nav_area, 1)

        # Footer: API status + version
        footer = QWidget()
        footer.setStyleSheet("background:transparent;border:none")
        footer_lay = QVBoxLayout(footer)
        footer_lay.setContentsMargins(16, 12, 16, 16)
        footer_lay.setSpacing(8)

        # API status row
        api_row = QHBoxLayout()
        api_row.setSpacing(8)
        self._sidebar_dot = GlowDot(_C["green"], 7)
        api_row.addWidget(self._sidebar_dot)

        self._api_info_widget = QVBoxLayout()
        self._api_info_widget.setSpacing(1)
        self._sidebar_api_label = QLabel("API 状态")
        self._sidebar_api_label.setStyleSheet(f"color:{_C['text3']};font-size:11px;background:transparent;border:none")
        self._api_info_widget.addWidget(self._sidebar_api_label)
        self._sidebar_api_name = QLabel("未配置")
        self._sidebar_api_name.setStyleSheet(f"color:{_C['text']};font-size:11px;font-weight:600;background:transparent;border:none")
        self._api_info_widget.addWidget(self._sidebar_api_name)
        api_row.addLayout(self._api_info_widget)
        api_row.addStretch()
        self._api_row_widgets = [self._sidebar_api_label, self._sidebar_api_name]
        footer_lay.addLayout(api_row)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{_C['border']};border:none")
        footer_lay.addWidget(sep)

        # Version
        self._ver_label = QLabel("ABC v0.1.0")
        self._ver_label.setStyleSheet(f"color:{_C['text3']};font-size:10px;background:transparent;border:none")
        footer_lay.addWidget(self._ver_label)

        lay.addWidget(footer)

        return sb

    def _toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        target_w = _SIDEBAR_COLLAPSED_W if self._sidebar_collapsed else _SIDEBAR_W

        # Show/hide text labels
        show = not self._sidebar_collapsed
        self._logo_card.setVisible(show)
        for w in self._api_row_widgets:
            w.setVisible(show)
        self._ver_label.setVisible(show)

        # Collapsed sidebar keeps only the icons; AnimatedButton centres the
        # icon automatically when its text is empty.
        for i, (name, _icon) in enumerate(self._NAV):
            self._nav_btns[i].setText("" if self._sidebar_collapsed else name)

        # A previous glide may still be running if the user double-clicks the
        # menu button; stop it or the two fight over the same property.
        for anim in self._sidebar_anims:
            stop_safely(anim)
        # setFixedWidth pins both bounds, so both have to be animated for the
        # sidebar to actually glide instead of snapping.
        self._sidebar_anims = [
            animate(self._sidebar, b"minimumWidth", target_w, duration=DUR_SLOW, easing=EASE_OUT),
            animate(self._sidebar, b"maximumWidth", target_w, duration=DUR_SLOW, easing=EASE_OUT),
        ]

    def _sync_indicator(self) -> None:
        """Snap the indicator onto the active button without animating."""
        self._place_indicator(animated=False)

    def _place_indicator(self, idx: int | None = None, *, animated: bool) -> None:
        stack = getattr(self, "_stack", None)
        if stack is None or not getattr(self, "_nav_btns", None):
            return
        if idx is None:
            idx = stack.currentIndex()
        button = self._nav_btns[idx]
        target = QRect(button.x(), button.y(), button.width(), button.height())
        if target.width() <= 0 or target.height() <= 0:
            return
        stop_safely(self._indicator_anim)
        self._indicator_anim = None
        if animated and self._nav_indicator.isVisible():
            self._indicator_anim = animate_geometry(
                self._nav_indicator, target, duration=DUR_SLOW, easing=EASE_OUT,
            )
        else:
            self._nav_indicator.setGeometry(target)
        self._nav_indicator.show()

    def _switch_page(self, idx: int) -> None:
        if idx == self._stack.currentIndex():
            self._place_indicator(idx, animated=True)
            return

        self._fader.capture()
        self._stack.setCurrentIndex(idx)
        self._fader.release(DUR_BASE)

        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        self._page_title.setText(self._NAV[idx][0])
        self._page_subtitle.setText(self._NAV_SUBTITLES[idx])
        self._place_indicator(idx, animated=True)

    # ── Top Bar ──────────────────────────────────────────────────────────

    def _mk_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setObjectName("topbar")
        bar.setStyleSheet(f"""
            QFrame#topbar {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #ffffff, stop:1 {_C['bg2']});
                border-bottom: 1px solid {_C['border']};
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(16)

        # Menu button — toggles sidebar
        menu_btn = AnimatedButton(icon="menu", variant="flat")
        menu_btn.setFixedSize(34, 34)
        menu_btn.clicked.connect(self._toggle_sidebar)
        lay.addWidget(menu_btn)

        # Title + subtitle
        self._page_title = QLabel("首页")
        self._page_title.setStyleSheet(f"color:{_C['text']};font-size:18px;font-weight:800;background:transparent;border:none")
        lay.addWidget(self._page_title)
        self._page_subtitle = QLabel(self._NAV_SUBTITLES[0])
        self._page_subtitle.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        lay.addWidget(self._page_subtitle)

        lay.addStretch()

        # Live time — started/stopped by showEvent so it idles in the tray.
        self._time_label = QLabel()
        self._time_label.setStyleSheet(
            f"color:{_C['text']};font-size:12px;font-weight:500;background:transparent;"
            "border:none;font-variant-numeric:tabular-nums"
        )
        lay.addWidget(self._time_label)
        self._time_timer = QTimer(self)
        self._time_timer.timeout.connect(self._tick_clock)
        self._tick_clock()

        # Status dot
        lay.addSpacing(12)
        self._status_dot = GlowDot(_C["green"], 8)
        lay.addWidget(self._status_dot)

        self._header_status = QLabel("就绪")
        self._header_status.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none")
        lay.addWidget(self._header_status)

        return bar

    _WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")

    def _tick_clock(self) -> None:
        now = time.localtime()
        self._time_label.setText(
            f"{time.strftime('%Y-%m-%d %H:%M:%S', now)} 星期{self._WEEKDAYS[now.tm_wday]}"
        )

    # ── Bottom Bar ───────────────────────────────────────────────────────

    def _mk_bottombar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setObjectName("bottombar")
        bar.setStyleSheet(f"""
            QFrame#bottombar {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {_C['bg2']}, stop:1 #ffffff);
                border-top: 1px solid {_C['border']};
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)

        # Status dot + text
        self._bottom_dot = GlowDot(_C["green"], 6)
        lay.addWidget(self._bottom_dot)
        self._bottom_status = QLabel("运行中 · 一切正常")
        self._bottom_status.setStyleSheet(f"color:{_C['text2']};font-size:11px;background:transparent;border:none")
        lay.addWidget(self._bottom_status)

        lay.addStretch()

        # Config saved time
        self._saved_time = QLabel("配置已保存")
        self._saved_time.setStyleSheet(f"color:{_C['text3']};font-size:10px;background:transparent;border:none")
        lay.addWidget(self._saved_time)

        # Pause button — warm yellow while paused
        self._pause_btn = AnimatedButton(
            "暂停", icon="pause", variant="ghost", small=True,
            checkable=True, warm_checked=True,
        )
        self._pause_btn.toggled.connect(self._on_pause)
        lay.addWidget(self._pause_btn)

        # Save button
        self._save_btn = AnimatedButton("保存配置", icon="check", variant="primary", small=True)
        self._save_btn.clicked.connect(self._save_settings)
        _shadow(self._save_btn, level=1)
        lay.addWidget(self._save_btn)

        # Exit button
        quit_btn = AnimatedButton("退出", icon="x", variant="danger", small=True)
        quit_btn.clicked.connect(self.quitRequested.emit)
        lay.addWidget(quit_btn)

        return bar

    # ── Home Page ────────────────────────────────────────────────────────

    def _page_home(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")

        page = QWidget()
        page.setStyleSheet(f"background:{_C['bg']}")
        root_lay = QVBoxLayout(page)
        root_lay.setContentsMargins(24, 20, 24, 20)
        root_lay.setSpacing(16)

        # Greeting banner
        self._greeting = GreetingBanner()
        root_lay.addWidget(self._greeting)

        # Main layout: left content + right panel
        home_layout = QHBoxLayout()
        home_layout.setSpacing(16)

        # Left column
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        # Row 1: 4 stat cards
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self._card_total = StatCard("弹幕总数", "0", _C["accent"], icon="💬")
        self._card_ai = StatCard("AI 生成", "0", _C["accent2"], icon="🤖", yellow=True)
        self._card_mock = StatCard("模拟弹幕", "0", _C["accent2"], icon="📋")
        self._card_pool = StatCard("缓存池弹幕", "0", _C["accent"], yellow=True)
        for c in (self._card_total, self._card_ai, self._card_mock, self._card_pool):
            row1.addWidget(c)
        left_col.addLayout(row1)

        # Row 2: 4 stat cards
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self._card_uptime = StatCard("运行时长", "--", _C["text3"], icon="⏱")
        self._card_captures = StatCard("截屏次数", "0", _C["text3"], icon="📸", yellow=True)
        self._card_tokens = StatCard("Token 消耗", "0", _C["accent"], icon="🔢")
        self._card_resp = StatCard("API 响应", "—", _C["text3"], icon="⚡", yellow=True)
        for c in (self._card_uptime, self._card_captures, self._card_tokens, self._card_resp):
            row2.addWidget(c)
        left_col.addLayout(row2)

        # Provider card
        self._api_card = ApiStatusCard()
        left_col.addWidget(self._api_card)

        left_col.addStretch()
        home_layout.addLayout(left_col, 1)
        root_lay.addLayout(home_layout, 1)

        scroll.setWidget(page)

        # Stats timer — refresh every 1 second
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.setInterval(1000)

        return scroll

    # ── API Page ─────────────────────────────────────────────────────────

    def _page_api(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")

        page = QWidget()
        page.setStyleSheet(f"background:{_C['bg']}")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)

        # Provider form card
        form_card = SectionCard("提供商设置")
        form_card._layout.setSpacing(10)

        self._api_prov = NoScrollComboBox()
        self._api_prov.setStyleSheet(_COMBO_STYLE)
        for sp in SUPPORTED_PROVIDERS:
            self._api_prov.addItem(sp.label, sp.key)
        self._api_prov.currentIndexChanged.connect(self._on_api_page_prov)
        form_card.add_row("提供商", self._api_prov)

        self._api_url = QLineEdit()
        self._api_url.setPlaceholderText("https://api.example.com/v1")
        self._api_url.setStyleSheet(LINE_EDIT_STYLE)
        form_card.add_row("Base URL", self._api_url)

        self._api_mdl = NoScrollComboBox()
        self._api_mdl.setStyleSheet(_COMBO_STYLE)
        self._api_mdl.setEditable(True)
        form_card.add_row("模型", self._api_mdl)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("Ollama / 自定义可留空")
        self._api_key.setStyleSheet(LINE_EDIT_STYLE)
        form_card.add_row("API Key", self._api_key)
        lay.addWidget(form_card)

        # Test + Save buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._api_test_btn = AnimatedButton("测试连接", icon="bolt", variant="ghost")
        self._api_test_btn.clicked.connect(self._test_api_on_page)
        btn_row.addWidget(self._api_test_btn)

        self._api_save_btn = AnimatedButton("保存配置", icon="check", variant="primary")
        _shadow(self._api_save_btn, level=1)
        self._api_save_btn.clicked.connect(self._save_api_on_page)
        btn_row.addWidget(self._api_save_btn)

        self._api_page_status = QLabel("")
        self._api_page_status.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        btn_row.addWidget(self._api_page_status, 1)
        lay.addLayout(btn_row)

        # History
        hist_card = SectionCard("历史配置")
        self._api_hist = QListWidget()
        self._api_hist.setMaximumHeight(140)
        self._api_hist.setStyleSheet(f"""
            QListWidget {{
                background: rgba(159,130,253,0.04);
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 6px;
                font-size: 12px;
                color: {_C['text2']};
            }}
            QListWidget::item {{
                padding: 6px 10px;
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background: rgba(159,130,253,0.15);
                color: {_C['text']};
            }}
        """)
        self._api_hist.itemDoubleClicked.connect(self._load_history_on_page)
        hist_card.add_widget(self._api_hist)

        del_row = QHBoxLayout()
        del_btn = AnimatedButton("删除选中", icon="trash", variant="danger", small=True)
        del_btn.clicked.connect(self._delete_history_on_page)
        del_row.addStretch()
        del_row.addWidget(del_btn)
        hist_card.add_layout(del_row)
        lay.addWidget(hist_card)

        lay.addStretch()
        scroll.setWidget(page)

        # Load current settings
        self._load_api_page()
        self._refresh_api_page_history()
        return scroll

    # ── Settings Page ────────────────────────────────────────────────────

    def _page_settings(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")

        page = QWidget()
        page.setStyleSheet(f"background:{_C['bg']}")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        # Barrage settings (merged: density, display, speed, opacity)
        card1 = SectionCard("💬 弹幕设置")
        self._density = NoScrollComboBox()
        self._density.setStyleSheet(_COMBO_STYLE)
        self._density.setFixedWidth(240)
        for label, val in [("低", "low"), ("中", "medium"), ("高", "high")]:
            self._density.addItem(label, val)
        self._density.currentTextChanged.connect(lambda: self.densityChanged.emit(self._density.currentData()))
        density_wrap = QWidget()
        density_wrap.setStyleSheet("background:transparent;border:none")
        dw_lay = QHBoxLayout(density_wrap)
        dw_lay.setContentsMargins(0, 0, 0, 0)
        dw_lay.addWidget(self._density)
        dw_lay.addStretch()
        card1.add_row("弹幕密度", density_wrap)

        # Helper: label | slider | value
        def _slider_row(label_text: str, slider: QWidget, val_widget: QLabel) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(64)
            lbl.setStyleSheet(f"color:{_C['text2']};font-size:12px;font-weight:500;background:transparent;border:none")
            row.addWidget(lbl)
            row.addWidget(slider, 1)
            row.addWidget(val_widget)
            return row

        self._display_area = TickedSlider(_DISPLAY_AREA_LABELS)
        self._display_area.valueChanged.connect(lambda v: self.displayAreaChanged.emit(_DISPLAY_AREA_VALUES[v]))
        card1.add_layout(_slider_row("显示区域", self._display_area, self._display_area.value_label()))

        self._font_size = TickedSlider(_FONT_SIZE_LABELS)
        self._font_size.valueChanged.connect(lambda v: self.fontSizeChanged.emit(_FONT_SIZE_PX[v]))
        card1.add_layout(_slider_row("字体大小", self._font_size, self._font_size.value_label()))

        self._opacity_slider = NoScrollSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.setStyleSheet(_STEP_SLIDER_STYLE)
        self._opacity_val = QLabel("100%")
        self._opacity_val.setFixedWidth(40)
        self._opacity_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._opacity_val.setStyleSheet(f"color:{_C['text']};font-size:12px;font-weight:600;background:transparent;border:none")
        self._opacity_slider.valueChanged.connect(lambda v: (
            self._opacity_val.setText(f"{v}%"), self.opacityChanged.emit(v)))
        card1.add_layout(_slider_row("不透明度", self._opacity_slider, self._opacity_val))

        self._speed = TickedSlider(_SPEED_LABELS)
        self._speed.valueChanged.connect(self.speedChanged.emit)
        card1.add_layout(_slider_row("移动速度", self._speed, self._speed.value_label()))

        self._mock_ck = ModernToggle("无 API Key 时使用模拟弹幕")
        card1.add_widget(self._mock_ck)
        lay.addWidget(card1)

        # Screen
        card3 = SectionCard("🔍 屏幕感知")
        self._ocr_ck = ModernToggle("启用 OCR 屏幕文字识别（需要 Tesseract）")
        self._win_ck = ModernToggle("检测前台窗口标题和应用分类")
        self._vision_ck = ModernToggle("将截图发送给 AI 分析画面内容（视觉模式）")
        card3.add_widget(self._ocr_ck)
        card3.add_widget(self._win_ck)
        card3.add_widget(self._vision_ck)
        lay.addWidget(card3)

        # API (shortcut to dedicated page)
        card4 = SectionCard("🔗 API 配置")
        api_row = QHBoxLayout()
        api_row.setSpacing(10)
        self._api_summary = QLabel("未配置 — 将使用模拟弹幕")
        self._api_summary.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        api_row.addWidget(self._api_summary, 1)
        api_btn = AnimatedButton("配置", icon="arrow_r", variant="ghost", small=True)
        api_btn.clicked.connect(lambda: self._switch_page(1))
        api_row.addWidget(api_btn)
        card4.add_layout(api_row)
        lay.addWidget(card4)

        # Advanced
        card5 = SectionCard("⚙ 高级设置")
        adv_row = QHBoxLayout()
        adv_row.setSpacing(16)

        def _adv_item(label_text: str, widget: QWidget) -> QVBoxLayout:
            col = QVBoxLayout()
            col.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color:{_C['text3']};font-size:11px;background:transparent;border:none")
            col.addWidget(lbl)
            col.addWidget(widget)
            return col

        self._privacy = NoScrollComboBox()
        self._privacy.setStyleSheet(_COMBO_STYLE)
        for label, val in [("严格", "strict"), ("均衡", "balanced")]:
            self._privacy.addItem(label, val)
        adv_row.addLayout(_adv_item("隐私模式", self._privacy))

        self._cost = NoScrollComboBox()
        self._cost.setStyleSheet(_COMBO_STYLE)
        for label, val in [("沉浸", "immersive"), ("均衡", "balanced"), ("节省", "saving")]:
            self._cost.addItem(label, val)
        adv_row.addLayout(_adv_item("成本模式", self._cost))

        self._cap_int = QDoubleSpinBox()
        self._cap_int.setRange(0.5, 30)
        self._cap_int.setSingleStep(0.5)
        self._cap_int.setSuffix(" 秒")
        self._cap_int.setFixedWidth(100)
        adv_row.addLayout(_adv_item("截屏间隔", self._cap_int))

        card5.add_layout(adv_row)
        lay.addWidget(card5)

        lay.addStretch()
        scroll.setWidget(page)
        return scroll

    # ── Logs Page ────────────────────────────────────────────────────────

    def _page_logs(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background:{_C['bg']}")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)


        tab_bar = QHBoxLayout()
        tab_bar.setSpacing(4)
        self._log_pages: list[QPlainTextEdit] = []
        self._log_stack = QStackedWidget()

        self._log_tabs = SegmentedTabs(["系统", "OCR", "API"])
        self._log_tabs.currentChanged.connect(self._log_stack.setCurrentIndex)
        tab_bar.addWidget(self._log_tabs)

        for _name in ("系统", "OCR", "API"):
            te = QPlainTextEdit()
            te.setReadOnly(True)
            te.setMaximumBlockCount(500)
            te.setStyleSheet(f"""
                QPlainTextEdit {{
                    background: #f8f7fc;
                    color: {_C['text3']};
                    font-family: "Cascadia Code", Consolas, monospace;
                    font-size: 12px;
                    border: 1px solid {_C['border']};
                    border-radius: 12px;
                    padding: 12px;
                    selection-background-color: {_C['accent']}25;
                }}
            """)
            self._log_pages.append(te)
            self._log_stack.addWidget(te)

        tab_bar.addStretch()

        clear_btn = AnimatedButton("清空", icon="trash", variant="danger", small=True)
        clear_btn.clicked.connect(lambda: [te.clear() for te in self._log_pages])
        tab_bar.addWidget(clear_btn)

        lay.addLayout(tab_bar)
        lay.addWidget(self._log_stack, 1)
        return page

    # ── About Page ───────────────────────────────────────────────────────

    def _page_about(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")

        page = QWidget()
        page.setStyleSheet(f"background:{_C['bg']}")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)


        # Hero
        hero = QFrame()
        hero.setStyleSheet(f"""
            QFrame {{
                background: {_C['surface_y']};
                border: 1px solid {_C['border_y']};
                border-radius: 16px;
            }}
        """)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(6)

        t = QLabel("AI Barrage Companion")
        t.setStyleSheet(f"color:{_C['text']};font-size:20px;font-weight:800;background:transparent;border:none")
        hl.addWidget(t)

        v = QLabel("版本 0.1.0  ·  GPL-3.0 License")
        v.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        hl.addWidget(v)

        d = QLabel("通过截屏分析屏幕活动（游戏、编程、看视频），利用 AI 生成符合场景的直播弹幕评论，在透明悬浮层上滚动显示。")
        d.setWordWrap(True)
        d.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none;line-height:1.5")
        hl.addWidget(d)
        lay.addWidget(hero)

        # Info cards — stacked vertically (no horizontal overflow)
        def _make_tag_text(items: list[str]) -> str:
            return "  ·  ".join(items)

        pc = SectionCard("🎭 内置人格")
        pt = QLabel(_make_tag_text(["杠精·爱挑刺", "暖场·鼓励加油", "吐槽·冷幽默", "跟风·复读", "整活·造梗"]))
        pt.setWordWrap(True)
        pt.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none;line-height:1.6")
        pc.add_widget(pt)
        lay.addWidget(pc)

        tc = SectionCard("🔧 技术栈")
        tt = QLabel(_make_tag_text(["Python 3.9+", "PySide6 (Qt)", "mss 截屏", "httpx", "Pillow", "pytesseract"]))
        tt.setWordWrap(True)
        tt.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none;line-height:1.6")
        tc.add_widget(tt)
        lay.addWidget(tc)

        prc = SectionCard("🧠 AI 供应商")
        pv = QLabel(_make_tag_text(["OpenAI", "DeepSeek", "Qwen", "Kimi", "GLM", "SiliconFlow", "OpenRouter", "MiMo", "Ollama"]))
        pv.setWordWrap(True)
        pv.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none;line-height:1.6")
        prc.add_widget(pv)
        lay.addWidget(prc)

        cr = SectionCard("📄 开源地址")
        gh = QLabel(f'<a href="https://github.com/Riordon666/AI-Barrage-Companion" style="color:{_C["accent"]};font-size:12px;text-decoration:none">GitHub →</a>')
        gh.setOpenExternalLinks(True)
        gh.setStyleSheet("background:transparent;border:none;margin-top:6px")
        cr.add_widget(gh)
        lay.addWidget(cr)

        lay.addStretch()
        scroll.setWidget(page)
        return scroll

    # ── Actions ──────────────────────────────────────────────────────────

    def _refresh_stats(self) -> None:
        ctrl = getattr(self, '_controller', None)
        if ctrl is None:
            return
        st = ctrl.stats
        self._card_total.set_value(str(st["barrages_sent"]))
        self._card_ai.set_value(str(st["barrages_ai"]))
        self._card_mock.set_value(str(st["barrages_mock"]))
        self._card_captures.set_value(str(st["captures"]))
        self._card_tokens.set_value(str(st['tokens_approx_in'] + st['tokens_approx_out']))

        uptime = int(ctrl.session_uptime)
        h, rem = divmod(uptime, 3600)
        m, sec = divmod(rem, 60)
        self._card_uptime.set_value(f"{h}h {m}m {sec}s" if h > 0 else f"{m}m {sec}s")

        # API response time (from real latency measurement)
        # API response time: show EMA-smoothed average
        if getattr(ctrl, '_latency_ema_s', 0) > 0:
            self._card_resp.set_value(f"{ctrl._latency_ema_s:.1f}s")

        # Cache pool count
        self._card_pool.set_value(str(getattr(ctrl, '_ai_buf_count', 0)))

        # API status card
        a = self._settings.api
        if a and a.provider:
            online = st["api_failures"] <= st.get("api_calls", 1) // 2
            calls = str(st.get("api_calls", 0))
            total_req = st.get("api_calls", 0) + st.get("api_failures", 0)
            success = f"{(st.get('api_calls', 0) / max(total_req, 1) * 100):.1f}%" if total_req > 0 else "—"
            resp = f"{ctrl._latency_ema_s:.1f}s" if getattr(ctrl, '_latency_ema_s', 0) > 0 else "—"
            self._api_card.set_info(a.provider, a.model, a.base_url, online,
                                     resp_time=resp, call_count=calls, success_rate=success)
            self._sidebar_api_name.setText(f"{a.provider} · {a.model}"[:30])
            self._sidebar_dot.set_color(_C["green"] if online else _C["red"])
            self._status_dot.set_color(_C["green"] if online else _C["red"])
            self._bottom_dot.set_color(_C["green"] if online else _C["red"])
        else:
            self._api_card.set_info("未配置", "", "将使用模拟弹幕", False)
            self._sidebar_api_name.setText("未配置")
            self._sidebar_dot.set_color(_C["text3"])
            self._status_dot.set_color(_C["text3"])
            self._bottom_dot.set_color(_C["text3"])

    def _add_activity(self, color: str, desc: str, extra: str = "") -> None:
        ts = time.strftime("%H:%M:%S")
        self._activity_items.insert(0, (color, desc, f"{ts} · {extra}", extra))
        if len(self._activity_items) > 30:
            self._activity_items = self._activity_items[:30]

    def set_controller(self, ctrl) -> None:
        self._controller = ctrl
        if self.isVisible():
            self._stats_timer.start()

    def _on_pause(self, paused: bool) -> None:
        self._pause_btn.setText("继续" if paused else "暂停")
        self._pause_btn.set_icon("play" if paused else "pause")
        self.pauseChanged.emit(paused)
        self.set_status("已暂停" if paused else "运行中", "info")
        logger.info("弹幕%s", "暂停" if paused else "继续")

    def _open_api_dialog(self) -> None:
        self._switch_page(1)  # Navigate to API page

    def _refresh_api_summary(self) -> None:
        a = self._settings.api
        if a and a.provider:
            self._api_summary.setText(f"{a.provider} · {a.model}")
            self._api_summary.setStyleSheet(f"color:{_C['green']};font-size:12px;background:transparent;border:none")
        else:
            self._api_summary.setText("未配置 — 将使用模拟弹幕")
            self._api_summary.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")

    # ── API page helpers ───────────────────────────────────────────────

    def _load_api_page(self) -> None:
        a = self._settings.api
        if a is None:
            self._api_prov.setCurrentIndex(self._api_prov.findData("custom"))
            return
        idx = self._api_prov.findData(a.provider)
        if idx >= 0:
            self._api_prov.setCurrentIndex(idx)
        self._api_url.setText(a.base_url)
        self._api_mdl.setCurrentText(a.model)
        self._api_key.setText(a.api_key or "")

    def _on_api_page_prov(self) -> None:
        key = self._api_prov.currentData()
        preset = provider_for_key(key)
        if preset.base_url:
            self._api_url.setText(preset.base_url)
        self._api_mdl.clear()
        if preset.models:
            self._api_mdl.addItems(list(preset.models))
        self._api_key.setEnabled(preset.requires_api_key)
        if not preset.requires_api_key:
            self._api_key.setText("")

    def _test_api_on_page(self) -> None:
        c = ApiConfig(
            provider=self._api_prov.currentData(),
            base_url=self._api_url.text().strip(),
            model=self._api_mdl.currentText().strip(),
            api_key=self._api_key.text().strip(),
        )
        self._api_test_btn.setText("测试中…")
        self._api_test_btn.setEnabled(False)
        self._api_page_status.setText("")

        def _do_test() -> tuple[bool, str]:
            import httpx
            try:
                preset = provider_for_key(c.provider)
                if preset.protocol == "anthropic":
                    url = c.base_url.rstrip("/") + "/messages"
                    payload: dict = {"model": c.model or "claude-sonnet-4-20250514", "max_tokens": 1, "messages": [{"role": "user", "content": "Hi"}]}
                    headers = {"x-api-key": c.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"}
                else:
                    url = c.base_url.rstrip("/") + "/chat/completions"
                    payload = {"model": c.model or "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 1}
                    headers = {"Authorization": f"Bearer {c.api_key}", "Content-Type": "application/json"}
                r = httpx.post(url, json=payload, headers=headers, timeout=15)
                if r.status_code == 200:
                    return True, "连接成功"
                return False, f"HTTP {r.status_code}"
            except Exception as exc:
                return False, str(exc)

        executor = ThreadPoolExecutor(max_workers=1)
        def _on_done(fut):
            ok, msg = fut.result()
            self._api_test_btn.setText("测试连接")
            self._api_test_btn.setEnabled(True)
            if ok:
                self._api_page_status.setText("✓ " + msg)
                self._api_page_status.setStyleSheet(f"color:{_C['green']};font-size:12px;background:transparent;border:none")
            else:
                self._api_page_status.setText("✗ " + msg)
                self._api_page_status.setStyleSheet(f"color:{_C['red']};font-size:12px;background:transparent;border:none")
        fut = executor.submit(_do_test)
        fut.add_done_callback(_on_done)

    def _save_api_on_page(self) -> None:
        c = ApiConfig(
            provider=self._api_prov.currentData(),
            base_url=self._api_url.text().strip(),
            model=self._api_mdl.currentText().strip(),
            api_key=self._api_key.text().strip(),
        )
        self._settings.api = c
        # Update history
        history = [h for h in self._settings.api_history
                   if not (h.provider == c.provider and h.base_url == c.base_url and h.model == c.model)]
        history.insert(0, c)
        if len(history) > 10:
            history = history[:10]
        self._settings.api_history = history
        self._refresh_api_summary()
        self._refresh_api_page_history()
        self.set_status(f"API: {c.provider} · {c.model}", "success")
        self._save_settings()

    def _refresh_api_page_history(self) -> None:
        self._api_hist.clear()
        for h in self._settings.api_history:
            self._api_hist.addItem(f"{h.provider}  |  {h.model}  |  {h.base_url}")

    def _load_history_on_page(self) -> None:
        idx = self._api_hist.currentRow()
        if 0 <= idx < len(self._settings.api_history):
            h = self._settings.api_history[idx]
            pi = self._api_prov.findData(h.provider)
            if pi >= 0:
                self._api_prov.setCurrentIndex(pi)
            self._api_url.setText(h.base_url)
            self._api_mdl.setCurrentText(h.model)
            self._api_key.setText(h.api_key or "")

    def _delete_history_on_page(self) -> None:
        idx = self._api_hist.currentRow()
        if 0 <= idx < len(self._settings.api_history):
            del self._settings.api_history[idx]
            self._refresh_api_page_history()

    def _save_settings(self) -> None:
        self._settings.density = as_density(self._density.currentData())
        self._settings.use_mock_when_api_missing = self._mock_ck.isChecked()
        self._settings.enable_vision = self._vision_ck.isChecked()
        self._settings.enable_ocr = self._ocr_ck.isChecked()
        self._settings.enable_window_title = self._win_ck.isChecked()
        self._settings.privacy_mode = self._privacy.currentData()  # type:ignore[assignment]
        self._settings.cost_mode = self._cost.currentData()  # type:ignore[assignment]
        self._settings.capture_interval_seconds = self._cap_int.value()
        self._settings.display_area_percent = _DISPLAY_AREA_VALUES[self._display_area.value()]
        self._settings.font_size_level = self._font_size.value()
        self._settings.barrage_font_size = _FONT_SIZE_PX[self._font_size.value()]
        self._settings.opacity_percent = self._opacity_slider.value()
        self._settings.speed_level = self._speed.value()
        self.settingsSaved.emit(self._settings)

        # Persist to disk and only show success when the write actually succeeded.
        ok = True
        if self._settings_store is not None:
            ok = self._settings_store.save(self._settings)

        if ok:
            self._save_btn.setText("已保存")
            self._save_btn.set_variant("success")
            self._saved_time.setText(f"配置已保存 {time.strftime('%H:%M:%S')}")
            self.set_status("配置已保存", "success")
        else:
            self._save_btn.setText("保存失败")
            self._save_btn.set_variant("error")
            self._saved_time.setText(f"保存失败 {time.strftime('%H:%M:%S')} — 磁盘满或权限不足")
            self.set_status("保存失败！请检查磁盘空间或文件权限", "error")

        QTimer.singleShot(3000, lambda: (
            self._save_btn.setText("保存配置"),
            self._save_btn.set_variant("primary"),
        ))

    def _load_settings(self, s: AppSettings) -> None:
        idx = self._density.findData(s.density)
        if idx >= 0:
            self._density.setCurrentIndex(idx)
        # Map display_area_percent to nearest tick index
        da_idx = min(range(len(_DISPLAY_AREA_VALUES)),
                     key=lambda i: abs(_DISPLAY_AREA_VALUES[i] - s.display_area_percent))
        self._display_area.setValue(da_idx)
        # Map font_size to nearest tick index
        fs_idx = min(range(len(_FONT_SIZE_PX)),
                     key=lambda i: abs(_FONT_SIZE_PX[i] - s.barrage_font_size))
        if hasattr(s, 'font_size_level'):
            fs_idx = s.font_size_level
        self._font_size.setValue(fs_idx)
        self._opacity_slider.setValue(getattr(s, 'opacity_percent', 100))
        self._speed.setValue(getattr(s, 'speed_level', 2))
        self._mock_ck.setChecked(s.use_mock_when_api_missing)
        self._vision_ck.setChecked(s.enable_vision)
        self._ocr_ck.setChecked(s.enable_ocr)
        self._win_ck.setChecked(s.enable_window_title)
        idx = self._privacy.findData(s.privacy_mode)
        if idx >= 0:
            self._privacy.setCurrentIndex(idx)
        idx = self._cost.findData(s.cost_mode)
        if idx >= 0:
            self._cost.setCurrentIndex(idx)
        self._cap_int.setValue(s.capture_interval_seconds)
        self._refresh_api_summary()

    def set_status(self, msg: str, typ: str = "info") -> None:
        colors = {"info": _C["text3"], "success": _C["green"], "error": _C["red"]}
        self._bottom_status.setText(msg)
        self._bottom_status.setStyleSheet(f"color:{colors.get(typ, _C['text2'])};font-size:11px;background:transparent;border:none")
        if hasattr(self, '_header_status'):
            self._header_status.setText(msg)
        if hasattr(self, '_status_dot'):
            dot_colors = {"info": _C["green"], "success": _C["green"], "error": _C["red"]}
            self._status_dot.set_color(dot_colors.get(typ, _C["green"]))

    # ── Log collector ────────────────────────────────────────────────────

    def _connect_logger(self) -> None:
        get_emitter().newLog.connect(self._on_log)

    def _on_log(self, msg: str) -> None:
        if "[API" in msg or "[HTTP" in msg or "弹幕生成" in msg:
            self._log_pages[2].appendPlainText(msg + "\n")
            self._add_activity("purple", msg.split("|")[-1].strip()[:40], "API")
        elif "OCR" in msg or "识别" in msg:
            self._log_pages[1].appendPlainText(msg + "\n")
            self._add_activity("green", msg.split("|")[-1].strip()[:40], "OCR")
        else:
            self._log_pages[0].appendPlainText(msg + "\n")

    def append_ocr_log(self, msg: str) -> None:
        self._log_pages[1].appendPlainText(f"{time.strftime('%H:%M:%S')} | {msg}\n")

    def append_api_log(self, msg: str) -> None:
        self._log_pages[2].appendPlainText(f"{time.strftime('%H:%M:%S')} | {msg}\n")

    def add_activity_items(self, items: list[tuple[str, str]]) -> None:
        """Receive AI-generated barrages (activity panel removed, no-op)."""
        pass

    # ── Global Styles ────────────────────────────────────────────────────

    def _apply_global(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{
                background: {_C['bg']};
                color: {_C['text']};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
                font-size: 13px;
            }}
            QComboBox {{
                background: {_C['surface']};
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 7px 12px;
                min-height: 20px;
                font-size: 13px;
            }}
            QComboBox:focus {{ border-color: {_C['accent']}; }}
            QComboBox::drop-down {{ border: none; padding-right: 8px; }}
            QComboBox QAbstractItemView {{
                background: #f8f7fc;
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                selection-background-color: rgba(159,130,253,0.18);
                padding: 4px;
            }}
            QSpinBox, QDoubleSpinBox {{
                background: {_C['surface']};
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 6px 10px;
                font-size: 13px;
                min-height: 20px;
            }}
            QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {_C['accent']}; }}
            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                border: none;
                border-left: 1px solid {_C['border']};
                border-bottom: 1px solid {_C['border']};
                border-radius: 0 10px 0 0;
                background: rgba(159,130,253,0.06);
                width: 22px;
                height: 14px;
            }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                border: none;
                border-left: 1px solid {_C['border']};
                border-radius: 0 0 10px 0;
                background: rgba(159,130,253,0.06);
                width: 22px;
                height: 14px;
            }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                width: 10px;
                height: 6px;
            }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                width: 10px;
                height: 6px;
            }}
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background: rgba(159,130,253,0.15);
            }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 4px 2px 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {_C['border_l']};
                border-radius: 4px;
                min-height: 36px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {_C['accent']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """ + SLIDER_STYLE)
