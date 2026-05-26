"""Transparent PySide6 barrage overlay."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QLabel, QWidget

from app.models import TrackAssignment


class BarrageLabel(QLabel):
    """Label with a soft text outline for readability."""

    def __init__(self, text: str, parent: QWidget, font_size: int) -> None:
        super().__init__(text, parent)
        self.setFont(QFont("Microsoft YaHei", font_size, QFont.Weight.Bold))
        self.setStyleSheet("color: white; background: transparent;")
        self.adjustSize()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(0, 0, 0, 180))
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            painter.drawText(self.rect().translated(dx, dy), self.alignment(), self.text())
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(self.rect(), self.alignment(), self.text())


class PySideOverlayRenderer(QWidget):
    """Render scheduled barrage items as right-to-left animations."""

    def __init__(self) -> None:
        super().__init__()
        self._animations: list[QPropertyAnimation] = []
        self._labels: list[BarrageLabel] = []
        self._display_area_percent = 65
        self._font_size = 18
        self.setWindowTitle("AI Barrage Companion Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._fit_primary_screen()
        self.set_click_through(True)

    def show(self) -> None:  # type: ignore[override]
        self._fit_primary_screen()
        super().show()

    def render(self, assignments: list[TrackAssignment]) -> None:
        if self.barrage_region_height() <= 0:
            return
        for assignment in assignments:
            self._create_barrage(assignment)

    def set_display_options(self, display_area_percent: int, font_size: int) -> None:
        self._display_area_percent = max(0, min(100, display_area_percent))
        self._font_size = max(12, min(48, font_size))

    def barrage_region_height(self) -> int:
        return int(self.height() * self._display_area_percent / 100)

    def track_height(self) -> int:
        metrics = QFontMetrics(QFont("Microsoft YaHei", self._font_size, QFont.Weight.Bold))
        return max(24, metrics.height() + 8)

    def set_click_through(self, enabled: bool) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        if hasattr(Qt.WindowType, "WindowTransparentForInput"):
            flags = self.windowFlags()
            if enabled:
                flags |= Qt.WindowType.WindowTransparentForInput
            else:
                flags &= ~Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)

    def close(self) -> None:  # type: ignore[override]
        for animation in self._animations:
            animation.stop()
        super().close()

    def _fit_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 720)
            return
        self.setGeometry(screen.geometry())

    def _create_barrage(self, assignment: TrackAssignment) -> None:
        label = BarrageLabel(assignment.item.text, self, self._font_size)
        label.move(assignment.start_x, min(assignment.y, max(0, self.barrage_region_height() - label.height())))
        label.show()

        duration_ms = max(500, int(assignment.item.duration_seconds * 1000))
        animation = QPropertyAnimation(label, b"pos", self)
        animation.setDuration(duration_ms)
        animation.setStartValue(label.pos())
        animation.setEndValue(label.pos() - QPoint(assignment.start_x + label.width(), 0))
        animation.setEasingCurve(QEasingCurve.Type.Linear)
        animation.finished.connect(lambda lbl=label, anim=animation: self._cleanup(lbl, anim))
        self._labels.append(label)
        self._animations.append(animation)
        animation.start()

    def _cleanup(self, label: BarrageLabel, animation: QPropertyAnimation) -> None:
        if animation in self._animations:
            self._animations.remove(animation)
        if label in self._labels:
            self._labels.remove(label)
        label.deleteLater()
