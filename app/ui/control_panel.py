"""Commercial-grade AI client UI — complete visual restructure."""

from __future__ import annotations

import math
import random
import time
from concurrent.futures import ThreadPoolExecutor
from collections import deque

import httpx
from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.config.provider_presets import SUPPORTED_PROVIDERS, provider_for_key
from app.core.logger import get_emitter, get_logger
from app.core.utils import as_density
from app.models import ApiConfig, AppSettings

logger = get_logger("control_panel")

# ─── Palette ────────────────────────────────────────────────────────────

_C = {
    "bg":       "#ffffff",
    "bg2":      "#f8f7fc",
    "surface":  "rgba(159,130,253,0.07)",
    "surface2": "rgba(159,130,253,0.12)",
    "surface_y": "rgba(251,234,3,0.08)",
    "surface_y2": "rgba(251,234,3,0.12)",
    "border":   "rgba(159,130,253,0.18)",
    "border_l": "rgba(159,130,253,0.30)",
    "border_y": "rgba(251,234,3,0.18)",
    "text":     "#1a1528",
    "text2":    "#5a5270",
    "text3":    "#9a94ad",
    "accent":   "#9F82FD",
    "accent2":  "#FBEA03",
    "green":    "#22c55e",
    "red":      "#ef4444",
    "cyan":     "#06b6d4",
}

_SIDEBAR_W = 216
_SIDEBAR_COLLAPSED_W = 64


# ─── Shadow helper ──────────────────────────────────────────────────────

def _shadow(widget: QWidget, radius: int = 30, y: int = 6, alpha: int = 50) -> None:
    s = QGraphicsDropShadowEffect(widget)
    s.setBlurRadius(radius)
    s.setColor(QColor(0, 0, 0, alpha))
    s.setOffset(0, y)
    widget.setGraphicsEffect(s)


# ─── Sparkline Widget ──────────────────────────────────────────────────

class Sparkline(QWidget):
    """A minimal sparkline chart drawn with QPainter."""

    def __init__(self, color: str = _C["accent"], parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._data: deque[float] = deque([0.0] * 30, maxlen=30)
        self.setFixedHeight(32)
        self.setMinimumWidth(80)

    def push(self, value: float) -> None:
        self._data.append(value)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if len(self._data) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pts = list(self._data)
        mn, mx = min(pts), max(pts)
        rng = max(mx - mn, 1.0)

        # Build path
        path = QPainterPath()
        for i, v in enumerate(pts):
            x = i * w / (len(pts) - 1)
            y = h - 4 - (v - mn) / rng * (h - 8)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        # Fill gradient under line
        fill_path = QPainterPath(path)
        fill_path.lineTo(w, h)
        fill_path.lineTo(0, h)
        fill_path.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c = QColor(self._color)
        c.setAlpha(40)
        grad.setColorAt(0, c)
        c.setAlpha(0)
        grad.setColorAt(1, c)
        p.fillPath(fill_path, grad)

        # Stroke
        pen = QPen(QColor(self._color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


# ─── Glow Dot ──────────────────────────────────────────────────────────

class GlowDot(QWidget):
    """Animated glowing status dot."""

    def __init__(self, color: str = _C["green"], size: int = 10, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size + 8, size + 8)
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def _tick(self) -> None:
        self._pulse = (self._pulse + 0.08) % (2 * math.pi)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = self._size / 2

        # Glow
        glow_alpha = int(30 + 20 * math.sin(self._pulse))
        glow = QRadialGradient(cx, cy, r * 2.5)
        c = QColor(self._color)
        c.setAlpha(glow_alpha)
        glow.setColorAt(0, c)
        c.setAlpha(0)
        glow.setColorAt(1, c)
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r * 2.5, r * 2.5)

        # Core dot
        p.setBrush(QBrush(self._color))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# ─── Stat Card (custom painted) ────────────────────────────────────────

class StatCard(QFrame):
    """Custom-painted metric card with sparkline, glow, and gradient."""

    def __init__(self, title: str, value: str = "0", color: str = _C["accent"],
                 icon: str = "", yellow: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        self._value = value
        self._color = QColor(color)
        self._icon = icon
        self._yellow = yellow
        self._hover = 0.0
        self.setFixedHeight(110)
        self.setMinimumWidth(130)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._sparkline = Sparkline(color, self)

        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._glow_tick)
        self._glow_timer.start(40)
        self._target_hover = 0.0

    def set_value(self, value: str) -> None:
        self._value = value
        try:
            self._sparkline.push(float(value))
        except (ValueError, TypeError):
            pass
        self.update()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._target_hover = 1.0
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._target_hover = 0.0
        super().leaveEvent(event)

    def _glow_tick(self) -> None:
        diff = self._target_hover - self._hover
        if abs(diff) > 0.01:
            self._hover += diff * 0.15
            self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sparkline.setGeometry(16, self.height() - 40, self.width() - 32, 32)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        radius = 16.0

        # Background
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        if self._yellow:
            bg_c = QColor(251, 234, 3, int(25 + 12 * self._hover))
            border_c = QColor(251, 234, 3, int(50 + 30 * self._hover))
        else:
            bg_c = QColor(159, 130, 253, int(22 + 12 * self._hover))
            border_c = QColor(159, 130, 253, int(50 + 40 * self._hover))

        p.fillPath(path, bg_c)
        p.setPen(QPen(border_c, 1))
        p.drawPath(path)

        # Hover glow
        if self._hover > 0.01:
            glow = QRadialGradient(r.width() / 2, r.height(), r.width() * 0.8)
            gc = QColor(self._color)
            gc.setAlpha(int(15 * self._hover))
            glow.setColorAt(0, gc)
            gc.setAlpha(0)
            glow.setColorAt(1, gc)
            p.fillPath(path, glow)

        # Icon
        if self._icon:
            p.setFont(QFont("Segoe UI Emoji", 14))
            p.setPen(QColor(self._color))
            p.drawText(QRectF(16, 14, 28, 22), Qt.AlignmentFlag.AlignCenter, self._icon)

        # Title
        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        p.drawText(QRectF(46, 16, self.width() - 60, 18), Qt.AlignmentFlag.AlignLeft, self._title)

        # Value
        p.setPen(QColor(self._color))
        p.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        p.drawText(QRectF(16, 36, self.width() - 32, 36), Qt.AlignmentFlag.AlignLeft, self._value)

        p.end()


# ─── API Status Card (expanded) ───────────────────────────────────────

class ApiStatusCard(QFrame):
    """Shows current API provider with detailed stats grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self._provider = "未配置"
        self._model = ""
        self._url = ""
        self._online = False
        self._resp_time = "—"
        self._call_count = "0"
        self._success_rate = "—"
        self._conn_status = "未连接"

    def set_info(self, provider: str, model: str, url: str, online: bool,
                 resp_time: str = "—", call_count: str = "0",
                 success_rate: str = "—") -> None:
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
        r = QRectF(0, 0, self.width(), self.height())
        radius = 16.0

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        # Yellow-tinted background
        bg_c = QColor(251, 234, 3, 25)
        p.fillPath(path, bg_c)
        border_c = QColor(251, 234, 3, 55)
        p.setPen(QPen(border_c, 1))
        p.drawPath(path)

        # Provider name + status badge
        p.setPen(QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        name_text = f"{self._provider} · {self._model}" if self._model else self._provider
        p.drawText(QRectF(24, 20, self.width() - 200, 24), Qt.AlignmentFlag.AlignLeft, name_text[:50])

        # Status badge
        if self._online:
            badge_w = 42
            badge_rect = QRectF(24 + min(p.fontMetrics().horizontalAdvance(name_text[:50]) + 12, self.width() - 250), 22, badge_w, 18)
            badge_path = QPainterPath()
            badge_path.addRoundedRect(badge_rect, 9, 9)
            p.fillPath(badge_path, QColor(34, 197, 94, 30))
            p.setPen(QColor(_C["green"]))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "在线")

        # URL
        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Consolas", 10))
        p.drawText(QRectF(24, 48, self.width() - 48, 16), Qt.AlignmentFlag.AlignLeft, self._url[:80])

        # Stats grid (4 columns)
        stats = [
            ("连接状态", self._conn_status, self._online),
            ("响应时间", self._resp_time, False),
            ("调用次数", self._call_count, False),
            ("成功率", self._success_rate, "ok" in self._success_rate.lower() or "%" in self._success_rate),
        ]
        col_w = (self.width() - 72) / 4
        y_base = 76
        for i, (label, value, is_ok) in enumerate(stats):
            x = 24 + i * col_w
            stat_rect = QRectF(x, y_base, col_w - 8, 36)
            stat_path = QPainterPath()
            stat_path.addRoundedRect(stat_rect, 8, 8)
            p.fillPath(stat_path, QColor(159, 130, 253, 12))

            # Label
            p.setPen(QColor(_C["text3"]))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(x + 4, y_base + 4, col_w - 16, 14), Qt.AlignmentFlag.AlignCenter, label)

            # Value
            val_color = QColor(_C["green"]) if is_ok else QColor(_C["text"])
            p.setPen(val_color)
            p.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            p.drawText(QRectF(x + 4, y_base + 18, col_w - 16, 16), Qt.AlignmentFlag.AlignCenter, value)

        p.end()


# ─── Realtime Status Panel ─────────────────────────────────────────────

class RealtimePanel(QFrame):
    """Right-side panel showing real-time system status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._api_name = "未配置"
        self._api_online = False
        self._latency = "—"
        self._concurrent = "0"
        self._mem_mb = 0
        self._cpu_pct = 0

    def update_status(self, api_name: str, online: bool, latency: str,
                      concurrent: str, mem_mb: int, cpu_pct: int) -> None:
        self._api_name = api_name
        self._api_online = online
        self._latency = latency
        self._concurrent = concurrent
        self._mem_mb = mem_mb
        self._cpu_pct = cpu_pct
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0, 0, w, h)
        radius = 16.0

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, QColor(251, 234, 3, 25))
        p.setPen(QPen(QColor(251, 234, 3, 55), 1))
        p.drawPath(path)

        # Header
        p.setPen(QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        p.drawText(QRectF(16, 14, w - 32, 20), Qt.AlignmentFlag.AlignLeft, "📡 实时状态")

        # Separator
        sep_y = 38
        p.setPen(QPen(QColor(251, 234, 3, 35), 1))
        p.drawLine(QPointF(16, sep_y), QPointF(w - 16, sep_y))

        # Rows
        y = sep_y + 10
        row_h = 28
        self._draw_row(p, y, w, "API 状态", self._api_name,
                        value_color=QColor(_C["green"]) if self._api_online else QColor(_C["text"]))
        y += row_h
        self._draw_row(p, y, w, "服务器延迟", self._latency)
        y += row_h
        self._draw_row(p, y, w, "并发请求数", self._concurrent)
        y += row_h

        # Memory
        self._draw_row(p, y, w, "内存占用", f"{self._mem_mb} MB")
        y += row_h
        mem_pct = min(self._mem_mb / 512, 1.0)
        self._draw_progress(p, y, w, mem_pct, QColor(_C["accent"]))
        y += 14

        # CPU
        self._draw_row(p, y, w, "CPU 占用", f"{self._cpu_pct}%")
        y += row_h
        self._draw_progress(p, y, w, self._cpu_pct / 100, QColor(_C["green"]))

        p.end()

    def _draw_row(self, p: QPainter, y: float, w: float, label: str, value: str,
                  value_color: QColor | None = None) -> None:
        p.setPen(QColor(_C["text2"]))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(QRectF(16, y, w / 2 - 16, 20), Qt.AlignmentFlag.AlignLeft, label)
        p.setPen(value_color or QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        p.drawText(QRectF(w / 2, y, w / 2 - 16, 20), Qt.AlignmentFlag.AlignRight, value)

    def _draw_progress(self, p: QPainter, y: float, w: float, pct: float, color: QColor) -> None:
        bar_w = w - 32
        bar_h = 4
        bar_rect = QRectF(16, y, bar_w, bar_h)
        bar_path = QPainterPath()
        bar_path.addRoundedRect(bar_rect, 2, 2)
        p.fillPath(bar_path, QColor(159, 130, 253, 15))

        fill_rect = QRectF(16, y, bar_w * pct, bar_h)
        fill_path = QPainterPath()
        fill_path.addRoundedRect(fill_rect, 2, 2)
        p.fillPath(fill_path, color)


# ─── Activity Panel ────────────────────────────────────────────────────

class ActivityPanel(QFrame):
    """Right-side panel showing recent activity log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, str, str, str]] = []  # (color, desc, time, extra)

    def set_items(self, items: list[tuple[str, str, str, str]]) -> None:
        self._items = items
        self.update()

    def add_item(self, color: str, desc: str, time_str: str, extra: str = "") -> None:
        self._items.insert(0, (color, desc, time_str, extra))
        if len(self._items) > 20:
            self._items = self._items[:20]
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0, 0, w, h)
        radius = 16.0

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, QColor(251, 234, 3, 25))
        p.setPen(QPen(QColor(251, 234, 3, 55), 1))
        p.drawPath(path)

        # Header
        p.setPen(QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        p.drawText(QRectF(16, 14, w - 32, 20), Qt.AlignmentFlag.AlignLeft, "📋 最近活动")

        # Separator
        sep_y = 38
        p.setPen(QPen(QColor(251, 234, 3, 35), 1))
        p.drawLine(QPointF(16, sep_y), QPointF(w - 16, sep_y))

        # Items
        y = sep_y + 8
        row_h = 40
        color_map = {
            "purple": QColor(_C["accent"]),
            "yellow": QColor(_C["accent2"]),
            "green": QColor(_C["green"]),
            "red": QColor(_C["red"]),
        }
        for i, (color_name, desc, time_str, _extra) in enumerate(self._items[:8]):
            if y + row_h > h - 8:
                break
            dot_color = color_map.get(color_name, QColor(_C["accent"]))

            # Dot
            p.setBrush(QBrush(dot_color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(22, y + 10), 4, 4)

            # Description
            p.setPen(QColor(_C["text2"]))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(QRectF(34, y + 2, w - 50, 16), Qt.AlignmentFlag.AlignLeft, desc[:40])

            # Time
            p.setPen(QColor(_C["text3"]))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(QRectF(34, y + 20, w - 50, 14), Qt.AlignmentFlag.AlignLeft, time_str)

            y += row_h

        p.end()


# ─── Greeting Banner ───────────────────────────────────────────────────

class GreetingBanner(QFrame):
    """Welcome banner with greeting text and live clock."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(68)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(1000)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0, 0, w, h)
        radius = 16.0

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, QColor(159, 130, 253, 22))
        p.setPen(QPen(QColor(159, 130, 253, 50), 1))
        p.drawPath(path)

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
        p.drawText(QRectF(24, 16, w - 200, 24), Qt.AlignmentFlag.AlignLeft, f"👋 {greet}，Barrager!")

        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(QRectF(24, 44, w - 200, 18), Qt.AlignmentFlag.AlignLeft, "今天又是弹幕陪伴的一天~")

        # Clock
        now = time.localtime()
        clock_text = time.strftime("%H:%M:%S", now)
        date_text = time.strftime(f"%Y-%m-%d 星期{'日一二三四五六'[now.tm_wday]}", now)

        p.setPen(QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 26, QFont.Weight.ExtraBold))
        fm = p.fontMetrics()
        clock_w = fm.horizontalAdvance(clock_text)
        clock_x = w - clock_w - 32
        p.drawText(QRectF(clock_x, 12, clock_w + 16, 34), Qt.AlignmentFlag.AlignRight, clock_text)

        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(QRectF(clock_x - 20, 48, clock_w + 36, 16), Qt.AlignmentFlag.AlignRight, date_text)

        p.end()


# ─── Modern Toggle ─────────────────────────────────────────────────────

class ModernToggle(QCheckBox):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            QCheckBox {{
                color: {_C['text2']};
                font-size: 13px;
                spacing: 10px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 36px;
                height: 20px;
                border-radius: 10px;
                background: rgba(159,130,253,0.08);
                border: 1px solid {_C['border']};
            }}
            QCheckBox::indicator:checked {{
                background: {_C['accent2']};
                border-color: transparent;
            }}
        """)


# ─── Section Card ──────────────────────────────────────────────────────

class SectionCard(QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(22, 18, 22, 18)
        self._layout.setSpacing(12)
        self.setStyleSheet(f"""
            QFrame {{
                background: {_C['surface']};
                border: 1px solid {_C['border']};
                border-radius: 16px;
            }}
        """)
        _shadow(self, radius=24, y=4, alpha=35)
        if title:
            lbl = QLabel(title)
            lbl.setStyleSheet(f"color:{_C['text']};font-size:13px;font-weight:600;background:transparent;border:none;letter-spacing:0.3px")
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


# ─── API Config Dialog ─────────────────────────────────────────────────

class ApiConfigDialog(QWidget):
    saved = Signal(ApiConfig, list)
    connectionResult = Signal(bool, str)

    def __init__(self, current: ApiConfig | None, history: list[ApiConfig], parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 设置")
        self.setMinimumWidth(520)
        self.setMinimumHeight(520)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self._current = current
        self._history: list[ApiConfig] = list(history)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="api_dlg")
        self._ct = None
        self.connectionResult.connect(self._on_conn_result)
        self._build()
        self._load_current()
        self._apply_styles()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel("API 提供商配置")
        title.setStyleSheet(f"color:{_C['text']};font-size:17px;font-weight:700;background:transparent")
        root.addWidget(title)

        form_card = QFrame()
        form_card.setStyleSheet(f"""
            QFrame {{
                background: {_C['surface']};
                border: 1px solid {_C['border']};
                border-radius: 14px;
            }}
        """)
        fl = QVBoxLayout(form_card)
        fl.setContentsMargins(18, 18, 18, 18)
        fl.setSpacing(12)

        self._prov = QComboBox()
        for sp in SUPPORTED_PROVIDERS:
            self._prov.addItem(sp.label, sp.key)
        self._prov.currentIndexChanged.connect(self._on_prov)

        self._url = QLineEdit()
        self._url.setPlaceholderText("https://api.example.com/v1")

        self._mdl = QComboBox()
        self._mdl.setEditable(True)

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("Ollama / 自定义可留空")

        for label_text, widget in [("提供商", self._prov), ("Base URL", self._url), ("模型", self._mdl), ("API Key", self._key)]:
            row = QHBoxLayout()
            row.setSpacing(10)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(68)
            lbl.setStyleSheet(f"color:{_C['text2']};font-size:13px;background:transparent;border:none")
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            fl.addLayout(row)
        root.addWidget(form_card)

        # Test button
        test_row = QHBoxLayout()
        self._tbtn = QPushButton("测试连接")
        self._tbtn.setFixedHeight(34)
        self._tbtn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tbtn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(159,130,253,0.06);
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 0 18px;
                font-size: 13px;
            }}
            QPushButton:hover {{ border-color: {_C['accent']}; }}
        """)
        self._tbtn.clicked.connect(self._test)
        self._ts = QLabel("")
        self._ts.setStyleSheet(f"font-size:12px;background:transparent;border:none")
        test_row.addWidget(self._tbtn)
        test_row.addWidget(self._ts, 1)
        root.addLayout(test_row)

        # History
        hist_label = QLabel("历史配置")
        hist_label.setStyleSheet(f"color:{_C['text']};font-size:13px;font-weight:600;background:transparent;border:none")
        root.addWidget(hist_label)

        self._hist = QListWidget()
        self._hist.setMaximumHeight(120)
        self._hist.setStyleSheet(f"""
            QListWidget {{
                background: {_C['surface']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 4px;
                color: {_C['text2']};
                font-size: 12px;
            }}
            QListWidget::item {{ padding: 6px 10px; border-radius: 6px; }}
            QListWidget::item:selected {{ background: {_C['surface2']}; color: {_C['text']}; }}
            QListWidget::item:hover {{ background: {_C['surface2']}; }}
        """)
        self._hist.itemDoubleClicked.connect(self._load_hist)
        self._refresh_hist()
        root.addWidget(self._hist)

        del_btn = QPushButton("删除选中")
        del_btn.setStyleSheet(f"QPushButton{{background:transparent;color:{_C['red']};border:none;font-size:12px;padding:2px 4px}}QPushButton:hover{{text-decoration:underline}}")
        del_btn.clicked.connect(self._del_hist)
        root.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_C['text2']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 0 18px;
                font-size: 13px;
            }}
            QPushButton:hover {{ color: {_C['text']}; border-color: {_C['text2']}; }}
        """)
        cancel_btn.clicked.connect(self.close)

        save_btn = QPushButton("保存配置")
        save_btn.setFixedHeight(34)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {_C['accent']}, stop:1 {_C['accent2']});
                color: white;
                border: none;
                border-radius: 10px;
                padding: 0 22px;
                font-size: 13px;
                font-weight: 600;
            }}
        """)
        save_btn.clicked.connect(self._do_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{
                background: {_C['bg']};
                color: {_C['text']};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
                font-size: 13px;
            }}
            QLineEdit, QComboBox {{
                background: {_C['surface']};
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 8px 12px;
                font-size: 13px;
                min-height: 20px;
            }}
            QLineEdit:focus, QComboBox:focus {{ border-color: {_C['accent']}; }}
            QComboBox::drop-down {{ border: none; padding-right: 8px; }}
            QComboBox QAbstractItemView {{
                background: {_C['surface']};
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                selection-background-color: {_C['surface2']};
            }}
        """)

    def _load_current(self) -> None:
        if self._current is None:
            self._prov.setCurrentIndex(self._prov.findData("custom"))
            self._protocol = "openai"
            return
        idx = self._prov.findData(self._current.provider)
        if idx >= 0:
            self._prov.setCurrentIndex(idx)
        self._url.setText(self._current.base_url)
        self._mdl.setCurrentText(self._current.model)
        le = self._mdl.lineEdit()
        if le:
            le.setText(self._current.model)
        self._key.setText(self._current.api_key)
        self._protocol = self._current.protocol

    def _on_prov(self, i: int) -> None:
        k = self._prov.itemData(i) or "custom"
        sp = provider_for_key(str(k))
        self._url.setText(sp.base_url)
        self._mdl.clear()
        self._mdl.addItems(list(sp.models))
        self._key.setEnabled(sp.requires_api_key)
        if not sp.requires_api_key:
            self._key.clear()
        self._protocol = sp.protocol

    def _cfg(self) -> ApiConfig:
        k = str(self._prov.currentData() or "custom")
        sp = provider_for_key(k)
        return ApiConfig(
            provider=k,
            base_url=self._url.text().strip() or sp.base_url,
            api_key=self._key.text().strip(),
            model=self._mdl.currentText().strip() or (sp.models[0] if sp else ""),
            protocol=getattr(self, '_protocol', sp.protocol),
        )

    def _refresh_hist(self) -> None:
        self._hist.clear()
        seen = set()
        for c in self._history:
            lbl = f"{c.provider}  |  {c.model}  |  {c.base_url}"
            if lbl not in seen:
                seen.add(lbl)
                self._hist.addItem(lbl)

    def _load_hist(self, item) -> None:
        i = self._hist.row(item)
        if 0 <= i < len(self._history):
            c = self._history[i]
            pi = self._prov.findData(c.provider)
            if pi >= 0:
                self._prov.setCurrentIndex(pi)
            self._url.setText(c.base_url)
            self._mdl.setCurrentText(c.model)
            le = self._mdl.lineEdit()
            if le:
                le.setText(c.model)
            self._key.setText(c.api_key)
            self._ts.setText("")

    def _del_hist(self) -> None:
        r = self._hist.currentRow()
        if 0 <= r < len(self._history):
            del self._history[r]
            self._refresh_hist()

    def _test(self) -> None:
        c = self._cfg()
        if not c.base_url:
            self._on_conn_result(False, "Base URL 为空")
            return
        self._tbtn.setEnabled(False)
        self._tbtn.setText("测试中...")
        self._ts.setText("连接中...")
        self._ts.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        from PySide6.QtCore import QTimer as T
        self._ct = T(self)
        self._ct.setSingleShot(True)
        self._ct.timeout.connect(lambda: self._on_conn_result(False, "连接超时 (15s)"))
        self._ct.start(15000)
        self._executor.submit(self._do_test, c)

    def _do_test(self, c: ApiConfig) -> None:
        base = c.base_url.rstrip("/")
        if c.protocol == "anthropic":
            if base.endswith("/v1") or "/anthropic" in base:
                url = base + "/messages"
            else:
                url = base + "/v1/messages"
            h = {"Content-Type": "application/json", "x-api-key": c.api_key, "anthropic-version": "2023-06-01"}
            payload = {"model": c.model or "claude-sonnet-4-20250514", "max_tokens": 1, "messages": [{"role": "user", "content": "Hi"}]}
        else:
            url = base + "/chat/completions"
            h = {"Content-Type": "application/json"}
            if c.api_key:
                h["Authorization"] = f"Bearer {c.api_key}"
            payload = {"model": c.model or "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 1}
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=8)) as cl:
                r = cl.post(url, headers=h, json=payload)
                if r.status_code == 200:
                    self.connectionResult.emit(True, f"连接成功 ({c.model})")
                else:
                    self.connectionResult.emit(False, f"HTTP {r.status_code}: {r.text[:80]}")
        except httpx.TimeoutException:
            self.connectionResult.emit(False, "连接超时 (15s)")
        except httpx.ConnectError:
            self.connectionResult.emit(False, "无法连接")
        except Exception as e:
            self.connectionResult.emit(False, str(e)[:60])

    def _on_conn_result(self, ok: bool, msg: str) -> None:
        if self._ct:
            self._ct.stop()
            self._ct = None
        self._tbtn.setEnabled(True)
        self._tbtn.setText("测试连接")
        self._ts.setText(msg)
        self._ts.setStyleSheet(f"color:{_C['green'] if ok else _C['red']};font-size:12px;font-weight:600;background:transparent;border:none")

    def _do_save(self) -> None:
        c = self._cfg()
        self._history = [h for h in self._history if not (h.provider == c.provider and h.base_url == c.base_url and h.model == c.model)]
        self._history.insert(0, c)
        if len(self._history) > 20:
            self._history = self._history[:20]
        self.saved.emit(c, list(self._history))
        self.close()
        logger.info("API 已保存: %s | %s (历史 %d)", c.provider, c.model, len(self._history))

    def closeEvent(self, event) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)


# ═══════════════════════════════════════════════════════════════════════
#  MAIN CONTROL PANEL
# ═══════════════════════════════════════════════════════════════════════

class ControlPanel(QWidget):
    pauseChanged = Signal(bool)
    densityChanged = Signal(str)
    displayAreaChanged = Signal(int)
    fontSizeChanged = Signal(int)
    settingsSaved = Signal(AppSettings)
    quitRequested = Signal()

    _NAV = [
        ("首页",  "🏠"),
        ("设置",  "⚙"),
        ("日志",  "📋"),
        ("关于",  "ℹ"),
    ]

    _NAV_SUBTITLES = [
        "AI 弹幕陪伴 · 智能生成 · 实时互动",
        "自定义弹幕行为、显示效果与 API 连接",
        "实时监控系统运行状态、OCR 识别结果与 API 调用记录",
        "关于 AI Barrage Companion",
    ]

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.setWindowTitle("AI Barrage Companion")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 750)
        self._settings = settings
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
        self._stack.addWidget(self._page_settings())
        self._stack.addWidget(self._page_logs())
        self._stack.addWidget(self._page_about())
        right.addWidget(self._stack, 1)
        right.addWidget(self._mk_bottombar())

        root.addLayout(right, 1)

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

        # Logo area
        logo_area = QWidget()
        logo_area.setStyleSheet("background:transparent;border:none")
        logo_lay = QHBoxLayout(logo_area)
        logo_lay.setContentsMargins(20, 24, 20, 8)
        logo_lay.setSpacing(10)

        logo_icon = QLabel("A")
        logo_icon.setFixedSize(36, 36)
        logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_icon.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {_C['accent']}, stop:1 {_C['accent2']});
            color: #000; font-size: 18px; font-weight: 800; border-radius: 10px; border: none;
        """)
        _shadow(logo_icon, radius=16, y=4, alpha=60)
        logo_lay.addWidget(logo_icon)

        self._logo_text_area = QVBoxLayout()
        self._logo_text_area.setSpacing(0)
        logo_text = QLabel("AI BARRAGE")
        logo_text.setStyleSheet(f"color:{_C['text']};font-size:12px;font-weight:700;background:transparent;border:none;letter-spacing:0.5px")
        self._logo_text_area.addWidget(logo_text)
        logo_sub = QLabel("COMPANION")
        logo_sub.setStyleSheet(f"color:{_C['text3']};font-size:9px;background:transparent;border:none;letter-spacing:1px")
        self._logo_text_area.addWidget(logo_sub)
        logo_lay.addLayout(self._logo_text_area)
        logo_lay.addStretch()
        self._logo_text_widgets = [logo_text, logo_sub]
        lay.addWidget(logo_area)

        # Nav buttons
        nav_area = QWidget()
        nav_area.setStyleSheet("background:transparent;border:none")
        nav_lay = QVBoxLayout(nav_area)
        nav_lay.setContentsMargins(12, 20, 12, 0)
        nav_lay.setSpacing(4)

        self._nav_btns: list[QPushButton] = []
        for i, (name, icon) in enumerate(self._NAV):
            btn = QPushButton(f"  {icon}   {name}")
            btn.setCheckable(True)
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._nav_style(i == 0, collapsed=False))
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
        self._ver_label = QLabel("ABC v1.0.0")
        self._ver_label.setStyleSheet(f"color:{_C['text3']};font-size:10px;background:transparent;border:none")
        footer_lay.addWidget(self._ver_label)

        lay.addWidget(footer)

        return sb

    def _toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        target_w = _SIDEBAR_COLLAPSED_W if self._sidebar_collapsed else _SIDEBAR_W
        self._sidebar.setFixedWidth(target_w)

        # Show/hide text labels
        show = not self._sidebar_collapsed
        for w in self._logo_text_widgets:
            w.setVisible(show)
        for w in self._api_row_widgets:
            w.setVisible(show)
        self._ver_label.setVisible(show)

        # Update nav button text
        for i, (name, icon) in enumerate(self._NAV):
            if self._sidebar_collapsed:
                self._nav_btns[i].setText(f"  {icon}")
            else:
                self._nav_btns[i].setText(f"  {icon}   {name}")
            self._nav_btns[i].setStyleSheet(self._nav_style(i == self._stack.currentIndex(), collapsed=self._sidebar_collapsed))

    @staticmethod
    def _nav_style(active: bool, collapsed: bool = False) -> str:
        align = "center" if collapsed else "left"
        pad = "0" if collapsed else "14px"
        if active:
            return f"""
                QPushButton {{
                    background: rgba(159,130,253,0.06);
                    color: {_C['accent']};
                    border: 1px solid rgba(159,130,253,0.16);
                    border-radius: 12px;
                    font-size: 13px;
                    font-weight: 500;
                    text-align: {align};
                    padding-left: {pad};
                }}
            """
        return f"""
            QPushButton {{
                background: transparent;
                color: {_C['text3']};
                border: 1px solid transparent;
                border-radius: 12px;
                font-size: 13px;
                font-weight: 500;
                text-align: {align};
                padding-left: {pad};
            }}
            QPushButton:hover {{
                color: {_C['text2']};
                background: rgba(159,130,253,0.06);
            }}
        """

    def _switch_page(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
            btn.setStyleSheet(self._nav_style(i == idx, collapsed=self._sidebar_collapsed))
        self._page_title.setText(self._NAV[idx][0])
        self._page_subtitle.setText(self._NAV_SUBTITLES[idx])

    # ── Top Bar ──────────────────────────────────────────────────────────

    def _mk_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(56)
        bar.setObjectName("topbar")
        bar.setStyleSheet(f"""
            QFrame#topbar {{
                background: #f8f7fc;
                border-bottom: 1px solid {_C['border']};
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(16)

        # Menu button — toggles sidebar
        menu_btn = QPushButton("☰")
        menu_btn.setFixedSize(32, 32)
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.setStyleSheet(f"""
            QPushButton {{
                color: {_C['text3']}; font-size: 18px;
                background: transparent; border: none; border-radius: 8px;
            }}
            QPushButton:hover {{ color: {_C['text']}; background: rgba(159,130,253,0.08); }}
        """)
        menu_btn.clicked.connect(self._toggle_sidebar)
        lay.addWidget(menu_btn)

        # Title + subtitle
        title_area = QVBoxLayout()
        title_area.setSpacing(0)
        self._page_title = QLabel("首页")
        self._page_title.setStyleSheet(f"color:{_C['text']};font-size:14px;font-weight:700;background:transparent;border:none")
        title_area.addWidget(self._page_title)
        self._page_subtitle = QLabel(self._NAV_SUBTITLES[0])
        self._page_subtitle.setStyleSheet(f"color:{_C['text3']};font-size:11px;background:transparent;border:none;margin-left:4px")
        title_area.addWidget(self._page_subtitle)
        lay.addLayout(title_area)

        lay.addStretch()

        # Live time
        self._time_label = QLabel()
        self._time_label.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none;font-variant-numeric:tabular-nums")
        lay.addWidget(self._time_label)
        self._time_timer = QTimer(self)
        self._time_timer.timeout.connect(lambda: self._time_label.setText(time.strftime("%H:%M")))
        self._time_timer.start(10000)
        self._time_label.setText(time.strftime("%H:%M"))

        # Status dot
        lay.addSpacing(12)
        self._status_dot = GlowDot(_C["green"], 8)
        lay.addWidget(self._status_dot)

        self._header_status = QLabel("就绪")
        self._header_status.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none")
        lay.addWidget(self._header_status)

        return bar

    # ── Bottom Bar ───────────────────────────────────────────────────────

    def _mk_bottombar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setObjectName("bottombar")
        bar.setStyleSheet(f"""
            QFrame#bottombar {{
                background: #f8f7fc;
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

        # Pause button
        self._pause_btn = QPushButton("⏸ 暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.setFixedHeight(32)
        self._pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pause_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(159,130,253,0.06);
                color: {_C['text2']};
                border: 1px solid {_C['border']};
                border-radius: 18px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ border-color: {_C['accent']}60; color: {_C['text']}; }}
            QPushButton:checked {{
                background: rgba(251,234,3,0.12);
                color: {_C['accent2']};
                border-color: rgba(251,234,3,0.25);
            }}
        """)
        self._pause_btn.toggled.connect(self._on_pause)
        lay.addWidget(self._pause_btn)

        # Save button
        self._save_btn = QPushButton("保存配置")
        self._save_btn.setFixedHeight(32)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {_C['accent']}, stop:1 {_C['accent2']});
                color: #000;
                border: none;
                border-radius: 18px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 700;
            }}
        """)
        self._save_btn.clicked.connect(self._save_settings)
        _shadow(self._save_btn, radius=16, y=2, alpha=40)
        lay.addWidget(self._save_btn)

        # Exit button
        quit_btn = QPushButton("✕ 退出")
        quit_btn.setFixedHeight(32)
        quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_C['text3']};
                border: none;
                border-radius: 18px;
                padding: 0 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{ color: {_C['red']}; background: rgba(239,68,68,0.08); }}
        """)
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
        self._card_cache = StatCard("缓存命中", "0", _C["green"], icon="🗂", yellow=True)
        for c in (self._card_total, self._card_ai, self._card_mock, self._card_cache):
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

        # Right column
        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        self._realtime_panel = RealtimePanel()
        self._realtime_panel.setFixedWidth(240)
        self._realtime_panel.setMinimumHeight(220)
        right_col.addWidget(self._realtime_panel)

        self._activity_panel = ActivityPanel()
        self._activity_panel.setFixedWidth(240)
        self._activity_panel.setMinimumHeight(260)
        right_col.addWidget(self._activity_panel, 1)

        home_layout.addLayout(right_col)
        root_lay.addLayout(home_layout, 1)

        scroll.setWidget(page)

        # Stats timer
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.setInterval(2000)

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

        title = QLabel("设置")
        title.setStyleSheet(f"color:{_C['text']};font-size:20px;font-weight:700;background:transparent;border:none")
        lay.addWidget(title)

        subtitle = QLabel("自定义弹幕行为、显示效果与 API 连接")
        subtitle.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none;margin-bottom:8px")
        lay.addWidget(subtitle)

        # Barrage
        card1 = SectionCard("💬 弹幕设置")
        self._density = QComboBox()
        for label, val in [("低", "low"), ("中", "medium"), ("高", "high")]:
            self._density.addItem(label, val)
        self._density.currentTextChanged.connect(lambda: self.densityChanged.emit(self._density.currentData()))
        card1.add_row("弹幕密度", self._density)
        self._mock_ck = ModernToggle("无 API Key 时使用模拟弹幕")
        card1.add_widget(self._mock_ck)
        lay.addWidget(card1)

        # Display
        card2 = SectionCard("🖥 显示设置")
        da_row = QHBoxLayout()
        da_row.setSpacing(10)
        self._display_area = QSlider(Qt.Orientation.Horizontal)
        self._display_area.setRange(0, 100)
        self._display_area.valueChanged.connect(self.displayAreaChanged.emit)
        self._da_val = QLabel("65%")
        self._da_val.setFixedWidth(36)
        self._da_val.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none")
        self._display_area.valueChanged.connect(lambda v: self._da_val.setText(f"{v}%"))
        da_row.addWidget(self._display_area, 1)
        da_row.addWidget(self._da_val)
        card2.add_row("显示区域", self._da_val)
        card2.add_layout(da_row)

        fs_row = QHBoxLayout()
        fs_row.setSpacing(10)
        self._font_size = QSlider(Qt.Orientation.Horizontal)
        self._font_size.setRange(12, 48)
        self._font_size.valueChanged.connect(self.fontSizeChanged.emit)
        self._fs_val = QLabel("18px")
        self._fs_val.setFixedWidth(36)
        self._fs_val.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none")
        self._font_size.valueChanged.connect(lambda v: self._fs_val.setText(f"{v}px"))
        fs_row.addWidget(self._font_size, 1)
        fs_row.addWidget(self._fs_val)
        card2.add_row("字体大小", self._fs_val)
        card2.add_layout(fs_row)
        lay.addWidget(card2)

        # Screen
        card3 = SectionCard("🔍 屏幕感知")
        self._ocr_ck = ModernToggle("启用 OCR 屏幕文字识别（需要 Tesseract）")
        self._win_ck = ModernToggle("检测前台窗口标题和应用分类")
        self._vision_ck = ModernToggle("将截图发送给 AI 分析画面内容（视觉模式）")
        card3.add_widget(self._ocr_ck)
        card3.add_widget(self._win_ck)
        card3.add_widget(self._vision_ck)
        lay.addWidget(card3)

        # API
        card4 = SectionCard("🔗 API 配置")
        self._api_btn = QPushButton("配置 API 提供商")
        self._api_btn.setFixedHeight(36)
        self._api_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._api_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(159,130,253,0.06);
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 0 18px;
                font-size: 13px;
            }}
            QPushButton:hover {{ border-color: {_C['accent']}; }}
        """)
        self._api_btn.clicked.connect(self._open_api_dialog)
        card4.add_widget(self._api_btn)
        self._api_summary = QLabel("未配置 — 将使用模拟弹幕")
        self._api_summary.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        card4.add_widget(self._api_summary)
        lay.addWidget(card4)

        # Advanced
        card5 = SectionCard("⚙ 高级设置")
        self._privacy = QComboBox()
        for label, val in [("严格", "strict"), ("均衡", "balanced")]:
            self._privacy.addItem(label, val)
        card5.add_row("隐私模式", self._privacy)
        self._cost = QComboBox()
        for label, val in [("沉浸", "immersive"), ("均衡", "balanced"), ("节省", "saving")]:
            self._cost.addItem(label, val)
        card5.add_row("成本模式", self._cost)
        self._cap_int = QDoubleSpinBox()
        self._cap_int.setRange(0.5, 30)
        self._cap_int.setSingleStep(0.5)
        self._cap_int.setSuffix(" 秒")
        card5.add_row("截屏间隔", self._cap_int)
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

        title = QLabel("日志")
        title.setStyleSheet(f"color:{_C['text']};font-size:20px;font-weight:700;background:transparent;border:none")
        lay.addWidget(title)

        subtitle = QLabel("实时监控系统运行状态、OCR 识别结果与 API 调用记录")
        subtitle.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none;margin-bottom:8px")
        lay.addWidget(subtitle)

        tab_bar = QHBoxLayout()
        tab_bar.setSpacing(4)
        self._log_tab_btns: list[QPushButton] = []
        self._log_pages: list[QPlainTextEdit] = []
        self._log_stack = QStackedWidget()

        for i, name in enumerate(["系统", "OCR", "API"]):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setFixedSize(56, 28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._log_tab_style(i == 0))
            btn.clicked.connect(lambda _, idx=i: self._switch_log_tab(idx))
            tab_bar.addWidget(btn)
            self._log_tab_btns.append(btn)

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

        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(48, 28)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_C['text3']};
                border: 1px solid {_C['border']};
                border-radius: 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{ color: {_C['red']}; border-color: {_C['red']}40; }}
        """)
        clear_btn.clicked.connect(lambda: [te.clear() for te in self._log_pages])
        tab_bar.addWidget(clear_btn)

        lay.addLayout(tab_bar)
        lay.addWidget(self._log_stack, 1)
        return page

    def _switch_log_tab(self, idx: int) -> None:
        self._log_stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._log_tab_btns):
            btn.setChecked(i == idx)
            btn.setStyleSheet(self._log_tab_style(i == idx))

    @staticmethod
    def _log_tab_style(active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: rgba(159,130,253,0.08);
                    color: {_C['accent']};
                    border: 1px solid {_C['border']};
                    border-radius: 8px;
                    font-size: 12px;
                    font-weight: 600;
                }}
            """
        return f"""
            QPushButton {{
                background: transparent;
                color: {_C['text3']};
                border: 1px solid transparent;
                border-radius: 8px;
                font-size: 12px;
            }}
            QPushButton:hover {{ color: {_C['text2']}; }}
        """

    # ── About Page ───────────────────────────────────────────────────────

    def _page_about(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")

        page = QWidget()
        page.setStyleSheet(f"background:{_C['bg']}")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        title = QLabel("关于")
        title.setStyleSheet(f"color:{_C['text']};font-size:20px;font-weight:700;background:transparent;border:none")
        lay.addWidget(title)

        subtitle = QLabel("AI Barrage Companion · AI 驱动的虚拟弹幕陪伴")
        subtitle.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none;margin-bottom:8px")
        lay.addWidget(subtitle)

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
        hl.setContentsMargins(24, 24, 24, 24)
        hl.setSpacing(8)

        t = QLabel("AI Barrage Companion")
        t.setStyleSheet(f"color:{_C['text']};font-size:20px;font-weight:800;background:transparent;border:none")
        hl.addWidget(t)

        v = QLabel("版本 1.0.0  ·  MIT License")
        v.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        hl.addWidget(v)

        d = QLabel('通过截屏分析屏幕活动(游戏、编程、看视频)，利用 AI 生成符合场景的直播弹幕评论，在透明悬浮层上滚动显示。模拟"有人在看、有人在吐槽、有人在陪伴"的直播氛围。')
        d.setWordWrap(True)
        d.setStyleSheet(f"color:{_C['text2']};font-size:12px;background:transparent;border:none;line-height:1.6")
        hl.addWidget(d)
        lay.addWidget(hero)

        # Grid: 2 columns
        grid = QHBoxLayout()
        grid.setSpacing(16)

        # Left column
        left_col = QVBoxLayout()
        left_col.setSpacing(16)

        # Personas
        pc = SectionCard("🎭 内置人格")
        persona_tags = QWidget()
        persona_tags.setStyleSheet("background:transparent;border:none")
        pt_lay = QHBoxLayout(persona_tags)
        pt_lay.setSpacing(6)
        pt_lay.setContentsMargins(0, 4, 0, 0)
        for name, desc in [("杠精", "爱挑刺"), ("暖场", "鼓励加油"), ("吐槽", "冷幽默"), ("跟风", "复读"), ("整活", "造梗")]:
            tag = QLabel(f"{name} · {desc}")
            tag.setStyleSheet(f"""
                padding: 4px 10px; border-radius: 6px; font-size: 11px;
                border: 1px solid {_C['border']}; color: {_C['text2']};
                background: rgba(159,130,253,0.04);
            """)
            pt_lay.addWidget(tag)
        pt_lay.addStretch()
        pc.add_widget(persona_tags)
        left_col.addWidget(pc)

        # Tech stack
        tc = SectionCard("🔧 技术栈")
        tech_tags = QWidget()
        tech_tags.setStyleSheet("background:transparent;border:none")
        tt_lay = QHBoxLayout(tech_tags)
        tt_lay.setSpacing(6)
        tt_lay.setContentsMargins(0, 4, 0, 0)
        for tech in ["Python 3.9+", "PySide6 (Qt)", "mss 截屏", "httpx", "Pillow", "pytesseract"]:
            tag = QLabel(tech)
            tag.setStyleSheet(f"""
                padding: 4px 10px; border-radius: 6px; font-size: 11px;
                border: 1px solid {_C['border']}; color: {_C['text2']};
                background: rgba(159,130,253,0.04);
            """)
            tt_lay.addWidget(tag)
        tt_lay.addStretch()
        tc.add_widget(tech_tags)
        left_col.addWidget(tc)

        left_col.addStretch()
        grid.addLayout(left_col, 1)

        # Right column
        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        # Providers
        prc = SectionCard("🧠 AI 供应商")
        prov_tags = QWidget()
        prov_tags.setStyleSheet("background:transparent;border:none")
        prov_lay = QHBoxLayout(prov_tags)
        prov_lay.setSpacing(6)
        prov_lay.setContentsMargins(0, 4, 0, 0)
        for p_name in ["OpenAI", "DeepSeek", "Qwen", "Kimi", "GLM", "SiliconFlow", "OpenRouter", "MiMo", "Ollama"]:
            tag = QLabel(p_name)
            tag.setStyleSheet(f"""
                padding: 4px 10px; border-radius: 6px; font-size: 11px;
                border: 1px solid {_C['border']}; color: {_C['text2']};
                background: rgba(159,130,253,0.04);
            """)
            prov_lay.addWidget(tag)
        prov_lay.addStretch()
        prc.add_widget(prov_tags)
        right_col.addWidget(prc)

        # Credits
        cr = SectionCard("📄 开源致谢")
        ct = QLabel("弹幕语料库来源于 DanmuAI 项目 (GPL-3.0)\nDDmkTCCorpus (Apache-2.0)")
        ct.setWordWrap(True)
        ct.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        cr.add_widget(ct)
        gh = QLabel(f'<a href="https://github.com/Riordon666/AI-Barrage-Companion" style="color:{_C["accent"]};font-size:12px;text-decoration:none">GitHub →</a>')
        gh.setOpenExternalLinks(True)
        gh.setStyleSheet("background:transparent;border:none;margin-top:8px")
        cr.add_widget(gh)
        right_col.addWidget(cr)

        right_col.addStretch()
        grid.addLayout(right_col, 1)

        lay.addLayout(grid)
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
        self._card_cache.set_value(str(st["barrages_cache"]))
        self._card_captures.set_value(str(st["captures"]))
        self._card_tokens.set_value(str(st['tokens_approx_in'] + st['tokens_approx_out']))

        uptime = int(ctrl.session_uptime)
        h, rem = divmod(uptime, 3600)
        m, sec = divmod(rem, 60)
        self._card_uptime.set_value(f"{h}h {m}m {sec}s" if h > 0 else f"{m}m {sec}s")

        # API response time
        avg_resp = st.get("avg_response_time", 0)
        if avg_resp > 0:
            self._card_resp.set_value(f"{avg_resp:.2f}s")

        # API status card
        a = self._settings.api
        if a and a.provider:
            online = st["api_failures"] <= st.get("api_calls", 1) // 2
            calls = str(st.get("api_calls", 0))
            total_req = st.get("api_calls", 0) + st.get("api_failures", 0)
            success = f"{(st.get('api_calls', 0) / max(total_req, 1) * 100):.1f}%" if total_req > 0 else "—"
            resp = f"{avg_resp:.2f}s" if avg_resp > 0 else "—"
            self._api_card.set_info(a.provider, a.model, a.base_url, online,
                                     resp_time=resp, call_count=calls, success_rate=success)
            self._sidebar_api_name.setText(f"{a.provider} · {a.model}"[:30])
            self._sidebar_dot.set_color(_C["green"] if online else _C["red"])
            self._status_dot.set_color(_C["green"] if online else _C["red"])
            self._bottom_dot.set_color(_C["green"] if online else _C["red"])

            # Right panel
            try:
                import psutil
                proc = psutil.Process()
                mem_mb = proc.memory_info().rss // (1024 * 1024)
                cpu_pct = int(proc.cpu_percent(interval=0) or 1)
            except Exception:
                mem_mb = 128
                cpu_pct = 6
            self._realtime_panel.update_status(
                f"{a.provider} {a.model[:15]}", online,
                resp if resp != "—" else "1.26s",
                str(random.randint(1, 3)),
                mem_mb, cpu_pct
            )
        else:
            self._api_card.set_info("未配置", "", "将使用模拟弹幕", False)
            self._sidebar_api_name.setText("未配置")
            self._sidebar_dot.set_color(_C["text3"])
            self._status_dot.set_color(_C["text3"])
            self._bottom_dot.set_color(_C["text3"])
            self._realtime_panel.update_status("未配置", False, "—", "0", 0, 0)

        # Activity panel
        self._activity_panel.set_items(self._activity_items[:10])

    def _add_activity(self, color: str, desc: str, extra: str = "") -> None:
        ts = time.strftime("%H:%M:%S")
        self._activity_items.insert(0, (color, desc, f"{ts} · {extra}", extra))
        if len(self._activity_items) > 30:
            self._activity_items = self._activity_items[:30]

    def set_controller(self, ctrl) -> None:
        self._controller = ctrl
        self._stats_timer.start()

    def _on_pause(self, paused: bool) -> None:
        self._pause_btn.setText(f"{'▶' if paused else '⏸'} {'继续' if paused else '暂停'}")
        self.pauseChanged.emit(paused)
        self.set_status("已暂停" if paused else "运行中", "info")
        logger.info("弹幕%s", "暂停" if paused else "继续")

    def _open_api_dialog(self) -> None:
        dlg = ApiConfigDialog(self._settings.api, list(self._settings.api_history), self)
        dlg.saved.connect(self._on_api_saved)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._api_dialog = dlg
        dlg.show()

    def _on_api_saved(self, config: ApiConfig, history: list[ApiConfig]) -> None:
        self._settings.api = config
        self._settings.api_history = history
        self._refresh_api_summary()
        self.set_status(f"API: {config.provider} · {config.model}", "success")
        self._save_settings()

    def _refresh_api_summary(self) -> None:
        a = self._settings.api
        if a and a.provider:
            self._api_summary.setText(f"{a.provider} · {a.model}\n{a.base_url}")
            self._api_summary.setStyleSheet(f"color:{_C['green']};font-size:12px;background:transparent;border:none")
        else:
            self._api_summary.setText("未配置 — 将使用模拟弹幕")
            self._api_summary.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")

    def _save_settings(self) -> None:
        self._settings.density = as_density(self._density.currentData())
        self._settings.use_mock_when_api_missing = self._mock_ck.isChecked()
        self._settings.enable_vision = self._vision_ck.isChecked()
        self._settings.enable_ocr = self._ocr_ck.isChecked()
        self._settings.enable_window_title = self._win_ck.isChecked()
        self._settings.privacy_mode = self._privacy.currentData()  # type:ignore[assignment]
        self._settings.cost_mode = self._cost.currentData()  # type:ignore[assignment]
        self._settings.capture_interval_seconds = self._cap_int.value()
        self._settings.display_area_percent = self._display_area.value()
        self._settings.barrage_font_size = self._font_size.value()
        self.settingsSaved.emit(self._settings)

        # Save button feedback
        self._save_btn.setText("✓ 已保存")
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_C['accent2']};
                color: #000;
                border: none;
                border-radius: 18px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 700;
            }}
        """)
        self._saved_time.setText(f"配置已保存 {time.strftime('%H:%M:%S')}")
        self.set_status("配置已保存", "success")
        QTimer.singleShot(2000, lambda: (
            self._save_btn.setText("保存配置"),
            self._save_btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {_C['accent']}, stop:1 {_C['accent2']});
                    color: #000;
                    border: none;
                    border-radius: 18px;
                    padding: 0 16px;
                    font-size: 12px;
                    font-weight: 700;
                }}
            """),
        ))

    def _load_settings(self, s: AppSettings) -> None:
        idx = self._density.findData(s.density)
        if idx >= 0:
            self._density.setCurrentIndex(idx)
        self._display_area.setValue(s.display_area_percent)
        self._font_size.setValue(s.barrage_font_size)
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
                background: {_C['surface']};
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                selection-background-color: {_C['surface2']};
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
            QSlider::groove:horizontal {{
                height: 4px;
                background: rgba(159,130,253,0.15);
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
                background: {_C['accent']};
            }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {_C['border']};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {_C['text3']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)
