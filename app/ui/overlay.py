"""Transparent PySide6 barrage overlay.

Each distinct barrage is rasterised **once** into a cached pixmap with its
halo, outline and fill already baked in; every frame after that is a plain
blit.  The whole screen is driven by a single timer that stops the moment the
last barrage leaves, so an idle overlay costs nothing at all.

Repainting is scoped to the strip each barrage sweeps through rather than the
whole window — important here, because a translucent full-screen repaint at
60fps would otherwise push megabytes of pixels per frame.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from time import perf_counter

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from app.models import TrackAssignment

# Speed level (0–4) → multiplier applied uniformly to every live barrage.
_SPEED_MUL = (0.5, 0.75, 1.0, 1.5, 2.0)

_FONT_FAMILY = "Microsoft YaHei"
_FRAME_MS = 16                # ~60fps
_GLYPH_PAD = 7                # room for the halo stroke around the glyphs
_FADE_PX = 90.0               # distance over which a barrage fades in / out
_MAX_SPRITES = 400            # hard ceiling, guards against runaway buffers
_CACHE_LIMIT = 512


class _Sprite:
    """One barrage in flight. Plain class + __slots__ — these churn fast."""

    __slots__ = ("pixmap", "x", "y", "w", "h", "speed", "spawn_x", "alpha")

    def __init__(
        self, pixmap: QPixmap, x: float, y: int, w: int, h: int, speed: float,
    ) -> None:
        self.pixmap = pixmap
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.speed = speed
        self.spawn_x = x
        self.alpha = 0.0


class PySideOverlayRenderer(QWidget):
    """Render scheduled barrage items as right-to-left animations."""

    def __init__(self) -> None:
        super().__init__()
        self._sprites: list[_Sprite] = []
        self._cache: OrderedDict[tuple[str, int, int], tuple[QPixmap, int, int]] = OrderedDict()
        self._display_area_percent = 65
        self._font_size = 18
        self._opacity_percent = 100
        self._speed_level = 2
        self._last_t = perf_counter()

        self.setWindowTitle("AI Barrage Companion Overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)

        self._fit_primary_screen()
        self.set_click_through(True)

    # ── lifecycle ───────────────────────────────────────────────────────

    def show(self) -> None:  # type: ignore[override]
        self._fit_primary_screen()
        super().show()

    def hide(self) -> None:  # type: ignore[override]
        self._timer.stop()
        self._sprites.clear()
        super().hide()

    def close(self) -> bool:  # type: ignore[override]
        self._timer.stop()
        self._sprites.clear()
        self._cache.clear()
        return super().close()

    # ── public API ──────────────────────────────────────────────────────

    def render(self, assignments: list[TrackAssignment]) -> None:
        if not self.isVisible():
            return  # hidden overlay: don't accumulate sprites or run the timer
        region_height = self.barrage_region_height()
        if region_height <= 0 or not assignments:
            return

        for assignment in assignments:
            if len(self._sprites) >= _MAX_SPRITES:
                break
            pixmap, width, height = self._pixmap_for(assignment.item.text)
            if width <= 0:
                continue
            y = max(0, min(assignment.y, region_height - height))
            # Honour the speed the manager assigned: it clamps each barrage to
            # the one ahead of it on the same track so they never overtake.
            speed = max(40.0, float(assignment.speed_px_per_second))
            self._sprites.append(
                _Sprite(pixmap, float(assignment.start_x), y, width, height, speed)
            )

        if self._sprites and not self._timer.isActive():
            self._last_t = perf_counter()
            self._timer.start(_FRAME_MS)

    def set_display_options(
        self,
        display_area_percent: int,
        font_size: int,
        opacity_percent: int = 100,
        speed_level: int = 2,
    ) -> None:
        self._display_area_percent = max(0, min(100, display_area_percent))
        self._font_size = max(12, min(48, font_size))
        self._opacity_percent = max(0, min(100, opacity_percent))
        self._speed_level = max(0, min(4, speed_level))
        self.setWindowOpacity(self._opacity_percent / 100.0)

    def set_opacity(self, percent: int) -> None:
        self._opacity_percent = max(0, min(100, percent))
        self.setWindowOpacity(self._opacity_percent / 100.0)

    def set_speed(self, level: int) -> None:
        # Applied per frame, so dragging the slider retimes barrages already
        # on screen instead of only affecting the next ones.
        self._speed_level = max(0, min(4, level))

    def barrage_region_height(self) -> int:
        return int(self.height() * self._display_area_percent / 100)

    def track_height(self) -> int:
        metrics = QFontMetricsF(self._font())
        return max(26, math.ceil(metrics.height()) + 12)

    def set_click_through(self, enabled: bool) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        if hasattr(Qt.WindowType, "WindowTransparentForInput"):
            flags = self.windowFlags()
            if enabled:
                flags |= Qt.WindowType.WindowTransparentForInput
            else:
                flags &= ~Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)

    # ── frame loop ──────────────────────────────────────────────────────

    def _step(self) -> None:
        now = perf_counter()
        # Clamp dt so a stalled main thread doesn't teleport every barrage.
        dt = min(0.05, now - self._last_t)
        self._last_t = now

        multiplier = _SPEED_MUL[self._speed_level]
        alive: list[_Sprite] = []

        for sprite in self._sprites:
            previous_x = sprite.x
            sprite.x -= sprite.speed * multiplier * dt
            sprite.alpha = self._alpha_for(sprite)

            # Repaint the strip the sprite just swept, so the trail is erased
            # and the new position drawn in one region.
            left = int(sprite.x) - 1
            right = int(previous_x) + sprite.w + 1
            self.update(left, sprite.y, right - left, sprite.h)

            if sprite.x + sprite.w > -4:
                alive.append(sprite)

        # Sprites dropped here are simply absent from the next paint, and the
        # update() above already queued their final position for clearing.
        self._sprites = alive
        if not self._sprites:
            self._timer.stop()

    @staticmethod
    def _alpha_for(sprite: _Sprite) -> float:
        travelled = sprite.spawn_x - sprite.x
        fade_in = travelled / _FADE_PX if travelled < _FADE_PX else 1.0
        trailing_edge = sprite.x + sprite.w
        fade_out = trailing_edge / _FADE_PX if trailing_edge < _FADE_PX else 1.0
        alpha = fade_in if fade_in < fade_out else fade_out
        return 0.0 if alpha < 0.0 else (1.0 if alpha > 1.0 else alpha)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        dirty = event.rect()

        # Explicitly punch the dirty region back to transparent. Relying on
        # Qt's translucent-background clear alone leaves trails on some
        # Windows compositor paths.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(dirty, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        if not self._sprites:
            painter.end()
            return

        left, right = dirty.left(), dirty.right()
        top, bottom = dirty.top(), dirty.bottom()
        for sprite in self._sprites:
            if sprite.x > right or sprite.x + sprite.w < left:
                continue
            if sprite.y > bottom or sprite.y + sprite.h < top:
                continue
            painter.setOpacity(sprite.alpha)
            painter.drawPixmap(QPointF(sprite.x, float(sprite.y)), sprite.pixmap)
        painter.end()

    # ── glyph rasterisation ─────────────────────────────────────────────

    def _font(self) -> QFont:
        return QFont(_FONT_FAMILY, self._font_size, QFont.Weight.Bold)

    def _pixmap_for(self, text: str) -> tuple[QPixmap, int, int]:
        """Return (pixmap, logical width, logical height) for *text*."""
        ratio = self.devicePixelRatioF() or 1.0
        key = (text, self._font_size, int(ratio * 100))
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        rendered = self._rasterise(text, ratio)
        self._cache[key] = rendered
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        return rendered

    def _rasterise(self, text: str, ratio: float) -> tuple[QPixmap, int, int]:
        font = self._font()
        metrics = QFontMetricsF(font)
        ascent = metrics.ascent()
        descent = metrics.descent()
        width = math.ceil(metrics.horizontalAdvance(text) + _GLYPH_PAD * 2)
        height = math.ceil(ascent + descent + _GLYPH_PAD * 2)
        if width <= 0 or height <= 0:
            return QPixmap(1, 1), 0, 0

        pixmap = QPixmap(int(width * ratio), int(height * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)

        path = QPainterPath()
        path.addText(QPointF(_GLYPH_PAD, _GLYPH_PAD + ascent), font, text)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Soft halo, then a crisp outline: keeps text legible over both a
        # bright editor and a dark game without a hard black keyline.
        painter.setPen(
            QPen(QColor(20, 14, 40, 52), 6.0, Qt.PenStyle.SolidLine,
                 Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPath(path)
        painter.setPen(
            QPen(QColor(12, 8, 26, 168), 2.6, Qt.PenStyle.SolidLine,
                 Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPath(path)

        gradient = QLinearGradient(0.0, _GLYPH_PAD, 0.0, _GLYPH_PAD + ascent + descent)
        gradient.setColorAt(0.0, QColor(255, 255, 255))
        gradient.setColorAt(1.0, QColor(231, 225, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(path)
        painter.end()

        return pixmap, width, height

    # ── geometry ────────────────────────────────────────────────────────

    def _fit_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 720)
            return
        self.setGeometry(screen.geometry())
