"""PySide application wiring for the MVP runtime."""

from __future__ import annotations

import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from app.config.settings_store import SettingsStore
from app.constants import (
    DEFAULT_AI_BARRAGE_COUNT,
    DEFAULT_BARRAGE_BUFFER_LIMIT,
    DEFAULT_BARRAGE_SEND_INTERVAL_MS,
    DEFAULT_RENDER_TICK_MS,
    DEFAULT_TRACK_GAP,
)
from app.core.ai_service import OpenAICompatibleBarrageService
from app.core.barrage_cache import InMemoryBarrageCache
from app.core.barrage_manager import BasicBarrageManager
from app.core.capture_scheduler import BasicCaptureScheduler
from app.core.frame_analyzer import BasicFrameAnalyzer
from app.core.mock_barrage_service import DEFAULT_PERSONAS, MockBarrageService
from app.core.privacy_guard import BasicPrivacyGuard
from app.core.screen_capture import MssScreenCapture
from app.models import AppSettings, BarrageItem, FrameStats, GenerationRequest, SceneSummary
from app.ui.control_panel import ControlPanel
from app.ui.overlay import PySideOverlayRenderer
from app.ui.tray import AppTray


class RuntimeController(QObject):
    """Coordinate capture, generation, scheduling, and rendering."""

    def __init__(
        self,
        settings: AppSettings,
        settings_store: SettingsStore,
        overlay: PySideOverlayRenderer,
        panel: ControlPanel,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._settings_store = settings_store
        self._overlay = overlay
        self._panel = panel
        self._capture = MssScreenCapture()
        self._analyzer = BasicFrameAnalyzer()
        self._capture_scheduler = BasicCaptureScheduler()
        self._privacy_guard = BasicPrivacyGuard()
        self._mock_generator = MockBarrageService()
        self._generator = self._build_generator()
        self._cache = InMemoryBarrageCache()
        self._overlay.set_display_options(
            settings.display_area_percent,
            settings.barrage_font_size,
        )
        self._manager = BasicBarrageManager(
            density=settings.density,
            track_height=self._overlay.track_height(),
        )
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._generation_future: Future[list[BarrageItem]] | None = None
        self._barrage_buffer: list[BarrageItem] = []
        self._last_stats: FrameStats | None = None
        self._last_scene = SceneSummary(
            activity="unknown",
            pace="normal",
            event="normal",
            confidence=0.0,
        )
        self._paused = False

        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self._capture_and_generate)
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_tick)
        self._send_timer = QTimer(self)
        self._send_timer.timeout.connect(self._send_next_barrage)

        panel.pauseChanged.connect(self.set_paused)
        panel.densityChanged.connect(self.set_density)
        panel.displayAreaChanged.connect(self.set_display_area)
        panel.fontSizeChanged.connect(self.set_font_size)
        panel.settingsSaved.connect(self.update_settings)
        panel.quitRequested.connect(QApplication.quit)

    def start(self) -> None:
        self._overlay.show()
        self._panel.show()
        self._render_timer.start(DEFAULT_RENDER_TICK_MS)
        self._send_timer.start(DEFAULT_BARRAGE_SEND_INTERVAL_MS)
        self._capture_and_generate()
        self._restart_capture_timer()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self._manager.pause()
            self._capture_timer.stop()
            self._send_timer.stop()
        else:
            self._manager.resume()
            self._send_timer.start(DEFAULT_BARRAGE_SEND_INTERVAL_MS)
            self._restart_capture_timer()

    def set_density(self, density: str) -> None:
        self._settings.density = density  # type: ignore[assignment]
        self._manager.set_density(density)

    def set_display_area(self, value: int) -> None:
        self._settings.display_area_percent = value
        self._overlay.set_display_options(value, self._settings.barrage_font_size)

    def set_font_size(self, value: int) -> None:
        self._settings.barrage_font_size = value
        self._overlay.set_display_options(self._settings.display_area_percent, value)
        self._manager.set_track_layout(self._overlay.track_height(), DEFAULT_TRACK_GAP)

    def update_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self._settings_store.save(settings)
        self._manager.set_density(settings.density)
        self._overlay.set_display_options(settings.display_area_percent, settings.barrage_font_size)
        self._manager.set_track_layout(self._overlay.track_height(), DEFAULT_TRACK_GAP)
        self._generator = self._build_generator()
        self._restart_capture_timer()

    def _capture_and_generate(self) -> None:
        if self._paused or self._generation_future is not None:
            return

        try:
            frame = self._capture.capture()
            self._last_stats, scene = self._analyzer.analyze(frame)
            decision = self._privacy_guard.sanitize(scene, self._settings)
            if not decision.allowed:
                return
            self._last_scene = decision.sanitized_scene
        except Exception:
            self._last_scene = SceneSummary(
                activity="unknown",
                pace="normal",
                event="normal",
                confidence=0.0,
            )

        cached = self._cache.get(self._last_scene, DEFAULT_AI_BARRAGE_COUNT)
        if len(cached) >= DEFAULT_AI_BARRAGE_COUNT and self._last_scene.event == "normal":
            self._buffer_items(cached)
            self._restart_capture_timer()
            return

        request = GenerationRequest(
            scene=self._last_scene,
            density=self._settings.density,
            personas=DEFAULT_PERSONAS,
            count=DEFAULT_AI_BARRAGE_COUNT,
        )
        self._generation_future = self._executor.submit(self._generate_items, request)
        self._restart_capture_timer()

    def _generate_items(self, request: GenerationRequest) -> list[BarrageItem]:
        result = self._generator.generate(request)
        if result.items:
            self._cache.put(request.scene, result.items)
        return result.items

    def _render_tick(self) -> None:
        if self._generation_future is not None and self._generation_future.done():
            try:
                self._buffer_items(self._generation_future.result())
            except Exception:
                pass
            self._generation_future = None

        if self._overlay.barrage_region_height() <= 0:
            return

        assignments = self._manager.tick(
            now=time.time(),
            viewport_width=max(1, self._overlay.width()),
            viewport_height=max(1, self._overlay.barrage_region_height()),
        )
        if assignments:
            self._overlay.render(assignments)

    def _send_next_barrage(self) -> None:
        if self._paused or not self._barrage_buffer:
            return
        self._manager.enqueue([self._barrage_buffer.pop(0)])

    def _buffer_items(self, items: list[BarrageItem]) -> None:
        capacity = max(0, DEFAULT_BARRAGE_BUFFER_LIMIT - len(self._barrage_buffer))
        if capacity <= 0:
            return
        self._barrage_buffer.extend(items[:capacity])

    def _restart_capture_timer(self) -> None:
        if self._paused:
            return
        policy = self._capture_scheduler.next_policy(self._last_stats, self._settings)
        interval_ms = int(policy.min_interval_seconds * 1000)
        self._capture_timer.start(max(500, interval_ms))

    def _build_generator(self) -> OpenAICompatibleBarrageService | MockBarrageService:
        if self._settings.api is None and self._settings.use_mock_when_api_missing:
            return self._mock_generator
        return OpenAICompatibleBarrageService(
            api_config=self._settings.api,
            fallback=self._mock_generator,
        )


def run_application(argv: list[str] | None = None) -> int:
    """Start the desktop application."""

    app = QApplication(argv or sys.argv)
    settings_store = SettingsStore()
    settings, warning = settings_store.load()
    overlay = PySideOverlayRenderer()
    panel = ControlPanel(settings)
    tray = AppTray(panel)
    controller = RuntimeController(settings, settings_store, overlay, panel)
    app.aboutToQuit.connect(controller.shutdown)

    if warning:
        print(warning)

    tray.show()
    controller.start()
    return app.exec()
