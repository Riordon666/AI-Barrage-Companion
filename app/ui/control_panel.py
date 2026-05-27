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
    "bg":         "#0b1220",
    "bg2":        "#0e1525",
    "surface":    "#131c2e",
    "surface2":   "#182438",
    "surface3":   "#1e2d45",
    "border":     "#1e2d45",
    "border_l":   "#263650",
    "text":       "#e8eaf0",
    "text2":      "#8b95a8",
    "text3":      "#5a6478",
    "accent":     "#4f7cff",
    "accent2":    "#7c5cff",
    "green":      "#34d399",
    "red":        "#f87171",
    "yellow":     "#fbbf24",
    "glow":       "#4f7cff",
}


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

    def __init__(self, title: str, value: str = "0", color: str = _C["accent"], parent=None):
        super().__init__(parent)
        self._title = title
        self._value = value
        self._color = QColor(color)
        self._hover = 0.0
        self.setFixedHeight(120)
        self.setMinimumWidth(160)
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

        # Background with subtle gradient
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        bg_grad = QLinearGradient(0, 0, self.width(), self.height())
        base = QColor(_C["surface"])
        hover = QColor(_C["surface2"])
        bg_grad.setColorAt(0, base)
        bg_grad.setColorAt(1, QColor(
            int(base.red() * (1 - self._hover) + hover.red() * self._hover),
            int(base.green() * (1 - self._hover) + hover.green() * self._hover),
            int(base.blue() * (1 - self._hover) + hover.blue() * self._hover),
        ))
        p.fillPath(path, bg_grad)

        # Border
        border_color = QColor(_C["border"])
        border_color.setAlpha(int(80 + 80 * self._hover))
        p.setPen(QPen(border_color, 1))
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

        # Top accent line
        accent_path = QPainterPath()
        accent_path.moveTo(radius, 0)
        accent_path.lineTo(self.width() - radius, 0)
        ac = QColor(self._color)
        ac.setAlpha(int(60 + 60 * self._hover))
        p.setPen(QPen(ac, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(accent_path)

        # Title
        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        p.drawText(QRectF(18, 16, self.width() - 36, 18), Qt.AlignmentFlag.AlignLeft, self._title)

        # Value
        p.setPen(QColor(self._color))
        p.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
        p.drawText(QRectF(18, 36, self.width() - 36, 42), Qt.AlignmentFlag.AlignLeft, self._value)

        p.end()


# ─── API Status Card ───────────────────────────────────────────────────

class ApiStatusCard(QFrame):
    """Shows current API provider with status and glow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self._provider = "未配置"
        self._model = ""
        self._url = ""
        self._online = False

    def set_info(self, provider: str, model: str, url: str, online: bool) -> None:
        self._provider = provider
        self._model = model
        self._url = url
        self._online = online
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        radius = 16.0

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        bg = QLinearGradient(0, 0, self.width(), 0)
        bg.setColorAt(0, QColor(_C["surface"]))
        bg.setColorAt(1, QColor(_C["surface2"]))
        p.fillPath(path, bg)
        p.setPen(QPen(QColor(_C["border"]), 1))
        p.drawPath(path)

        # Status dot
        dot_x, dot_y = 24, 30
        dot_r = 5
        color = QColor(_C["green"] if self._online else _C["text3"])
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(dot_x, dot_y), dot_r, dot_r)

        # Glow around dot
        if self._online:
            glow = QRadialGradient(dot_x, dot_y, 15)
            gc = QColor(_C["green"])
            gc.setAlpha(25)
            glow.setColorAt(0, gc)
            gc.setAlpha(0)
            glow.setColorAt(1, gc)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QPointF(dot_x, dot_y), 15, 15)

        # Provider name
        p.setPen(QColor(_C["text"]))
        p.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        p.drawText(QRectF(40, 18, self.width() - 60, 22), Qt.AlignmentFlag.AlignLeft, self._provider)

        # Model + URL
        detail = f"{self._model}  ·  {self._url}" if self._model else self._url
        p.setPen(QColor(_C["text3"]))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(QRectF(40, 42, self.width() - 60, 18), Qt.AlignmentFlag.AlignLeft, detail[:80])

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
                background: {_C['surface']};
                border: 1px solid {_C['border']};
            }}
            QCheckBox::indicator:checked {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {_C['accent']}, stop:1 {_C['accent2']});
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
                background: {_C['surface2']};
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
            QListWidget::item:hover {{ background: {_C['surface3']}; }}
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
            QPushButton:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {_C['accent']}, stop:1 #6d4de8); }}
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

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.setWindowTitle("AI Barrage Companion")
        self.setMinimumSize(900, 600)
        self.resize(960, 640)
        self._settings = settings
        self._build()
        self._apply_global()
        self._load_settings(settings)
        self._connect_logger()

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

    # ── Sidebar ──────────────────────────────────────────────────────────

    def _mk_sidebar(self) -> QFrame:
        sb = QFrame()
        sb.setFixedWidth(64)
        sb.setObjectName("sidebar")
        sb.setStyleSheet(f"""
            QFrame#sidebar {{
                background: rgba(8, 14, 26, 200);
                border-right: 1px solid {_C['border']};
            }}
        """)

        lay = QVBoxLayout(sb)
        lay.setContentsMargins(0, 16, 0, 12)
        lay.setSpacing(0)

        # Logo
        logo = QLabel("A")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"""
            color: transparent;
            font-size: 22px;
            font-weight: 800;
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {_C['accent']}, stop:1 {_C['accent2']});
            -webkit-background-clip: text;
            margin: 0 14px 4px 14px;
        """)
        # Fallback: just use accent color since Qt doesn't support background-clip
        logo.setStyleSheet(f"color:{_C['accent']};font-size:22px;font-weight:800;margin:0 14px 4px 14px;background:transparent;border:none")
        lay.addWidget(logo)

        sub = QLabel("ABC")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color:{_C['text3']};font-size:8px;letter-spacing:1px;margin-bottom:24px;background:transparent;border:none")
        lay.addWidget(sub)

        # Nav buttons
        self._nav_btns: list[QPushButton] = []
        for i, (name, icon) in enumerate(self._NAV):
            btn = QPushButton(icon)
            btn.setToolTip(name)
            btn.setCheckable(True)
            btn.setFixedSize(44, 44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._nav_style(i == 0))
            btn.clicked.connect(lambda _, idx=i: self._switch_page(idx))
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
            self._nav_btns.append(btn)
        self._nav_btns[0].setChecked(True)

        lay.addStretch()

        # Version
        ver = QLabel("v0.1")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(f"color:{_C['text3']};font-size:9px;background:transparent;border:none")
        lay.addWidget(ver)

        return sb

    @staticmethod
    def _nav_style(active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                        stop:0 rgba(79,124,255,25), stop:1 rgba(124,92,255,10));
                    color: {_C['accent']};
                    border: 1px solid rgba(79,124,255,40);
                    border-radius: 12px;
                    font-size: 18px;
                }}
            """
        return f"""
            QPushButton {{
                background: transparent;
                color: {_C['text3']};
                border: 1px solid transparent;
                border-radius: 12px;
                font-size: 18px;
            }}
            QPushButton:hover {{
                color: {_C['text2']};
                background: rgba(255,255,255,5);
            }}
        """

    def _switch_page(self, idx: int) -> None:
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
            btn.setStyleSheet(self._nav_style(i == idx))
        self._page_title.setText(self._NAV[idx][0])

    # ── Top Bar ──────────────────────────────────────────────────────────

    def _mk_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(52)
        bar.setObjectName("topbar")
        bar.setStyleSheet(f"""
            QFrame#topbar {{
                background: {_C['bg']};
                border-bottom: 1px solid {_C['border']};
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)

        self._page_title = QLabel("首页")
        self._page_title.setStyleSheet(f"color:{_C['text']};font-size:14px;font-weight:600;background:transparent;border:none")
        lay.addWidget(self._page_title)

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
        bar.setFixedHeight(48)
        bar.setObjectName("bottombar")
        bar.setStyleSheet(f"""
            QFrame#bottombar {{
                background: {_C['bg']};
                border-top: 1px solid {_C['border']};
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 0, 16, 0)

        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setCheckable(True)
        self._pause_btn.setFixedSize(36, 36)
        self._pause_btn.setToolTip("暂停 / 继续")
        self._pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pause_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_C['surface']};
                color: {_C['text2']};
                border: 1px solid {_C['border']};
                border-radius: 18px;
                font-size: 14px;
            }}
            QPushButton:hover {{ border-color: {_C['accent']}60; color: {_C['text']}; }}
            QPushButton:checked {{
                background: rgba(251,191,36,15);
                color: {_C['yellow']};
                border-color: rgba(251,191,36,40);
            }}
        """)
        self._pause_btn.toggled.connect(self._on_pause)
        lay.addWidget(self._pause_btn)

        lay.addStretch()

        self._status_bar = QLabel("就绪")
        self._status_bar.setStyleSheet(f"color:{_C['text3']};font-size:11px;background:transparent;border:none")
        lay.addWidget(self._status_bar)

        lay.addStretch()

        self._save_btn = QPushButton("保存")
        self._save_btn.setFixedSize(64, 32)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {_C['accent']}, stop:1 {_C['accent2']});
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5d8aff, stop:1 #8d6aff);
            }}
        """)
        self._save_btn.clicked.connect(self._save_settings)
        _shadow(self._save_btn, radius=16, y=2, alpha=40)
        lay.addWidget(self._save_btn)

        quit_btn = QPushButton("✕")
        quit_btn.setFixedSize(32, 32)
        quit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_C['text3']};
                border: none;
                border-radius: 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{ color: {_C['red']}; background: rgba(248,113,113,10); }}
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
        lay = QVBoxLayout(page)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(20)

        # Greeting
        greet = QLabel("仪表盘")
        greet.setStyleSheet(f"color:{_C['text']};font-size:20px;font-weight:700;background:transparent;border:none")
        lay.addWidget(greet)

        # Stat cards row
        row1 = QHBoxLayout()
        row1.setSpacing(14)
        self._card_total = StatCard("弹幕总数", "0", _C["accent"])
        self._card_ai = StatCard("AI 生成", "0", _C["accent2"])
        self._card_mock = StatCard("模拟弹幕", "0", _C["yellow"])
        self._card_cache = StatCard("缓存命中", "0", _C["green"])
        for c in (self._card_total, self._card_ai, self._card_mock, self._card_cache):
            row1.addWidget(c)
        lay.addLayout(row1)

        # Second row
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        self._card_uptime = StatCard("运行时长", "--", _C["text3"])
        self._card_captures = StatCard("截屏次数", "0", _C["text3"])
        self._card_tokens = StatCard("Token 消耗", "0", _C["accent"])
        for c in (self._card_uptime, self._card_captures, self._card_tokens):
            row2.addWidget(c)
        # Spacer to align with 4-column grid
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row2.addWidget(spacer)
        lay.addLayout(row2)

        # API status
        self._api_card = ApiStatusCard()
        lay.addWidget(self._api_card)

        lay.addStretch()
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

        # Barrage
        card1 = SectionCard("弹幕")
        self._density = QComboBox()
        for label, val in [("低", "low"), ("中", "medium"), ("高", "high")]:
            self._density.addItem(label, val)
        self._density.currentTextChanged.connect(lambda: self.densityChanged.emit(self._density.currentData()))
        card1.add_row("密度", self._density)
        self._mock_ck = ModernToggle("无 API Key 时使用模拟弹幕")
        card1.add_widget(self._mock_ck)
        lay.addWidget(card1)

        # Display
        card2 = SectionCard("显示")
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
        card3 = SectionCard("屏幕感知")
        self._ocr_ck = ModernToggle("启用 OCR 屏幕文字识别")
        self._win_ck = ModernToggle("启用窗口标题检测")
        self._vision_ck = ModernToggle("发送截图给 AI（视觉模式）")
        card3.add_widget(self._ocr_ck)
        card3.add_widget(self._win_ck)
        card3.add_widget(self._vision_ck)
        lay.addWidget(card3)

        # API
        card4 = SectionCard("API")
        self._api_btn = QPushButton("配置 API 提供商")
        self._api_btn.setFixedHeight(36)
        self._api_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._api_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_C['surface2']};
                color: {_C['text']};
                border: 1px solid {_C['border']};
                border-radius: 10px;
                padding: 0 18px;
                font-size: 13px;
            }}
            QPushButton:hover {{ border-color: {_C['accent']}60; }}
        """)
        self._api_btn.clicked.connect(self._open_api_dialog)
        card4.add_widget(self._api_btn)
        self._api_summary = QLabel("未配置 — 将使用模拟弹幕")
        self._api_summary.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        card4.add_widget(self._api_summary)
        lay.addWidget(card4)

        # Advanced
        card5 = SectionCard("高级")
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
                    background: #060a14;
                    color: #5a6a80;
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
                    background: {_C['surface']};
                    color: {_C['text']};
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

        # Hero
        hero = QFrame()
        hero.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 {_C['accent']}0c, stop:0.5 {_C['accent2']}0c, stop:1 transparent);
                border: 1px solid {_C['border']};
                border-radius: 18px;
            }}
        """)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(28, 24, 28, 24)
        hl.setSpacing(8)

        t = QLabel("AI Barrage Companion")
        t.setStyleSheet(f"color:{_C['text']};font-size:22px;font-weight:800;background:transparent;border:none")
        hl.addWidget(t)

        v = QLabel("版本 0.1.0  ·  MIT License")
        v.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        hl.addWidget(v)

        d = QLabel("通过截屏分析屏幕活动，利用 AI 生成直播弹幕评论，在透明覆盖层上滚动显示。")
        d.setWordWrap(True)
        d.setStyleSheet(f"color:{_C['text2']};font-size:13px;background:transparent;border:none;line-height:1.5")
        hl.addWidget(d)

        gh = QLabel('<a href="https://github.com/Riordon666/AI-Barrage-Companion" style="color:#4f7cff;font-size:12px">GitHub</a>')
        gh.setOpenExternalLinks(True)
        gh.setStyleSheet("background:transparent;border:none")
        hl.addWidget(gh)
        lay.addWidget(hero)

        # Personas
        pc = SectionCard("内置人格")
        for key, name, desc in [
            ("troll", "杠精", "爱挑刺、唱反调"),
            ("support", "暖场", "鼓励、加油、打气"),
            ("sarcastic", "吐槽", "犀利吐槽、冷幽默"),
            ("follower", "跟风", "附和、复读、跟队形"),
            ("fun", "整活", "搞怪、造梗、抖机灵"),
        ]:
            r = QLabel(f"<b style='color:{_C['text']}'>{name}</b>  <span style='color:{_C['text3']}'>({key})</span>  <span style='color:{_C['text2']}'>— {desc}</span>")
            r.setStyleSheet("font-size:12px;padding:3px 0;background:transparent;border:none")
            pc.add_widget(r)
        lay.addWidget(pc)

        # Providers
        prc = SectionCard("支持的 AI 供应商")
        for p in ["OpenAI", "DeepSeek", "阿里云百炼 / Qwen", "Moonshot / Kimi", "智谱 GLM",
                   "SiliconFlow", "OpenRouter", "小米 MiMo", "Ollama 本地", "自定义 OpenAI 兼容"]:
            r = QLabel(f"·  {p}")
            r.setStyleSheet(f"color:{_C['text2']};font-size:12px;padding:2px 0;background:transparent;border:none")
            prc.add_widget(r)
        lay.addWidget(prc)

        # Credits
        cr = SectionCard("开源致谢")
        ct = QLabel("弹幕语料库来源于 DanmuAI 项目 (GPL-3.0) 及 DDmkTCCorpus (Apache-2.0)。")
        ct.setWordWrap(True)
        ct.setStyleSheet(f"color:{_C['text3']};font-size:12px;background:transparent;border:none")
        cr.add_widget(ct)
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
        self._card_cache.set_value(str(st["barrages_cache"]))
        self._card_captures.set_value(str(st["captures"]))
        self._card_tokens.set_value(str(st['tokens_approx_in'] + st['tokens_approx_out']))

        uptime = int(ctrl.session_uptime)
        h, rem = divmod(uptime, 3600)
        m, sec = divmod(rem, 60)
        self._card_uptime.set_value(f"{h}h {m}m {sec}s" if h > 0 else f"{m}m {sec}s")

        # API status card
        a = self._settings.api
        if a and a.provider:
            online = st["api_failures"] <= st.get("api_calls", 1) // 2
            self._api_card.set_info(a.provider, a.model, a.base_url, online)
            self._status_dot.set_color(_C["green"] if online else _C["red"])
        else:
            self._api_card.set_info("未配置", "", "将使用模拟弹幕", False)
            self._status_dot.set_color(_C["text3"])

    def set_controller(self, ctrl) -> None:
        self._controller = ctrl
        self._stats_timer.start()

    def _on_pause(self, paused: bool) -> None:
        self._pause_btn.setText("▶" if paused else "⏸")
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
        self._save_btn.setText("✓")
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_C['green']};
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 14px;
                font-weight: 700;
            }}
        """)
        self.set_status("配置已保存", "success")
        QTimer.singleShot(1500, lambda: (
            self._save_btn.setText("保存"),
            self._save_btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {_C['accent']}, stop:1 {_C['accent2']});
                    color: white;
                    border: none;
                    border-radius: 16px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5d8aff, stop:1 #8d6aff);
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
        self._status_bar.setText(msg)
        self._status_bar.setStyleSheet(f"color:{colors.get(typ, _C['text3'])};font-size:11px;background:transparent;border:none")
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
        elif "OCR" in msg or "识别" in msg:
            self._log_pages[1].appendPlainText(msg + "\n")
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
                background: {_C['surface3']};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {_C['accent']}, stop:1 {_C['accent2']});
            }}
            QSlider::handle:horizontal:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #5d8aff, stop:1 #8d6aff); }}
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
