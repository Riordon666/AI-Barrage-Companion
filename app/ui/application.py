"""PySide application wiring for the MVP runtime."""

from __future__ import annotations

import random
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from app.config.settings_store import SettingsStore
from app.constants import (
    DEFAULT_AI_BARRAGE_COUNT,
    DEFAULT_BARRAGE_BUFFER_LIMIT,
    DEFAULT_BARRAGE_DURATION_SECONDS,
    DEFAULT_RENDER_TICK_MS,
    DEFAULT_TRACK_GAP,
    DENSITY_HIGHLIGHT_INTERVAL,
    DENSITY_SEND_INTERVAL,
    PERSONA_SPEED,
)
from app.core.ai_service import OpenAICompatibleBarrageService, encode_frame_jpeg_base64
from app.core.barrage_cache import InMemoryBarrageCache
from app.core.barrage_manager import BasicBarrageManager
from app.core.capture_scheduler import BasicCaptureScheduler
from app.core.frame_analyzer import BasicFrameAnalyzer
from app.core.logger import get_logger, setup_logging
from app.core.mock_barrage_service import DEFAULT_PERSONAS, MockBarrageService
from app.core.ocr_engine import OcrCache, extract_screen_text
from app.core.privacy_guard import BasicPrivacyGuard
from app.core.screen_capture import MssScreenCapture
from app.core.screen_context import capture_screen_context
from app.core.utils import as_density
from app.models import AppSettings, BarrageItem, Density, FrameStats, GenerationRequest, SceneSummary
from app.ui.control_panel import ControlPanel
from app.ui.overlay import PySideOverlayRenderer
from app.ui.tray import AppTray

logger = get_logger("application")


class RuntimeController(QObject):
    """Coordinate capture, generation, scheduling, and rendering."""

    def __init__(
        self,
        settings: AppSettings,
        settings_store: SettingsStore,
        overlay: PySideOverlayRenderer,
        panel: ControlPanel,
        *,
        capture: MssScreenCapture | None = None,
        analyzer: BasicFrameAnalyzer | None = None,
        capture_scheduler: BasicCaptureScheduler | None = None,
        privacy_guard: BasicPrivacyGuard | None = None,
        mock_generator: MockBarrageService | None = None,
        cache: InMemoryBarrageCache | None = None,
        manager: BasicBarrageManager | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._settings_store = settings_store
        self._overlay = overlay
        self._panel = panel
        self._capture = capture or MssScreenCapture()
        self._analyzer = analyzer or BasicFrameAnalyzer()
        self._capture_scheduler = capture_scheduler or BasicCaptureScheduler()
        self._privacy_guard = privacy_guard or BasicPrivacyGuard()
        self._mock_generator = mock_generator or MockBarrageService()
        self._generator = self._build_generator()
        self._cache = cache or InMemoryBarrageCache()
        self._overlay.set_display_options(
            settings.display_area_percent,
            settings.barrage_font_size,
        )
        self._manager = manager or BasicBarrageManager(
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
        self._ai_failures = 0  # consecutive AI generation failures
        self._ocr_cache = OcrCache()

        # -- Statistics & telemetry --
        self._session_start = time.time()
        self._stats = {
            "barrages_sent": 0,
            "barrages_ai": 0,
            "barrages_mock": 0,
            "barrages_cache": 0,
            "captures": 0,
            "api_calls": 0,
            "api_failures": 0,
            "tokens_approx_in": 0,
            "tokens_approx_out": 0,
        }
        self._last_ocr_text: str = ""
        self._last_api_request: str = ""
        self._last_api_response: str = ""

        self._capture_timer = QTimer(self)
        self._capture_timer.timeout.connect(self._capture_and_generate)
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self._render_tick)
        self._send_timer = QTimer(self)
        self._send_timer.setSingleShot(True)
        self._send_timer.timeout.connect(self._send_next_barrage)
        # Buffer fill timer: always runs to keep barrages flowing continuously.
        self._fill_timer = QTimer(self)
        self._fill_timer.timeout.connect(self._fill_buffer_tick)

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
        self._schedule_next_send()
        self._fill_timer.start(random.randint(400, 900))
        self._capture_and_generate()
        self._restart_capture_timer()
        source = "模拟弹幕" if isinstance(self._generator, MockBarrageService) else "AI"
        features: list[str] = [source]
        if self._settings.enable_ocr:
            features.append("OCR")
        if self._settings.enable_window_title:
            features.append("窗口检测")
        if self._settings.enable_vision:
            features.append("视觉模式")
        logger.info(
            "应用启动 | 弹幕来源=%s | 密度=%s | 特性=%s",
            source, self._settings.density, "+".join(features) if len(features) > 1 else features[0],
        )

        # --- Quick OCR self-test on first capture ---
        if self._settings.enable_ocr:
            try:
                frame = self._capture.capture()
                result = extract_screen_text(frame)
                if result:
                    self._panel.append_ocr_log(f"OCR 自检通过: 识别到 {len(result)} 字符")
                else:
                    self._panel.append_ocr_log(
                        "OCR 自检: 当前屏幕未识别到文字"
                    )
            except Exception:
                pass  # self-test is non-critical

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("应用关闭")

    # -- statistics (read by control panel) --

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def session_uptime(self) -> float:
        return time.time() - self._session_start

    @property
    def last_ocr_text(self) -> str:
        return self._last_ocr_text

    @property
    def last_api_request(self) -> str:
        return self._last_api_request

    @property
    def last_api_response(self) -> str:
        return self._last_api_response

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self._manager.pause()
            self._capture_timer.stop()
            self._send_timer.stop()
            self._fill_timer.stop()
            logger.info("已暂停 | 活跃弹幕=%d", self._manager.active_count)
        else:
            self._manager.resume()
            self._schedule_next_send()
            self._fill_timer.start(random.randint(400, 900))
            self._restart_capture_timer()
            logger.info("已恢复运行")

    def set_density(self, density: str) -> None:
        self._settings.density = as_density(density)
        self._manager.set_density(density)
        logger.info("密度切换为: %s", density)

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
        self._ai_failures = 0  # reset on settings change
        self._restart_capture_timer()
        self._fill_timer.start(random.randint(400, 900))
        source = "模拟弹幕" if isinstance(self._generator, MockBarrageService) else "AI"
        logger.info("配置已更新 | 弹幕来源=%s | 密度=%s", source, settings.density)

    def _capture_and_generate(self) -> None:
        if self._paused or self._generation_future is not None:
            return

        self._stats["captures"] += 1
        encoded_frame: str | None = None
        screen_context_text = ""

        try:
            frame = self._capture.capture()

            # --- OCR: extract readable text from the screenshot ---
            ocr_text = ""
            if self._settings.enable_ocr and not isinstance(self._generator, MockBarrageService):
                raw_text = extract_screen_text(frame)
                if raw_text and self._ocr_cache.should_send(raw_text):
                    ocr_text = raw_text
                    self._last_ocr_text = ocr_text
                    self._panel.append_ocr_log(
                        f"识别到 {len(ocr_text)} 字符，已发送:\n{ocr_text}"
                    )
                    logger.info("OCR 识别 %d 字符: %.80s", len(ocr_text), ocr_text)
                elif raw_text:
                    self._panel.append_ocr_log(
                        f"识别到 {len(raw_text)} 字符，重复内容已抑制:\n{raw_text[:120]}"
                    )
                else:
                    self._panel.append_ocr_log("OCR 扫描完成，未识别到文字")
            # -----------------------------------------------------

            # --- Window title context ---
            if self._settings.enable_window_title:
                ctx = capture_screen_context()
                if ctx.is_meaningful:
                    screen_context_text = ctx.description
                    logger.info("屏幕上下文: %s (%s)", ctx.description, ctx.app_category)

            if self._settings.enable_vision and not isinstance(self._generator, MockBarrageService):
                encoded_frame = encode_frame_jpeg_base64(frame)
            self._last_stats, scene = self._analyzer.analyze(frame)

            # Merge screen context sources into the scene summary.
            # OCR text is the most specific signal — prepend it.
            parts: list[str] = []
            if ocr_text:
                parts.append(f"屏幕文字: {ocr_text}")
            if screen_context_text:
                parts.append(screen_context_text)
            if parts:
                scene.screen_context = " | ".join(parts)

            decision = self._privacy_guard.sanitize(scene, self._settings)
            if not decision.allowed:
                logger.debug("隐私过滤阻止: blocked=%s", decision.blocked_fields)
                return
            self._last_scene = decision.sanitized_scene
            logger.info(
                "截屏分析 | activity=%s pace=%s event=%s confidence=%.2f context=%s",
                self._last_scene.activity, self._last_scene.pace,
                self._last_scene.event, self._last_scene.confidence,
                self._last_scene.screen_context[:80] if self._last_scene.screen_context else "(无)",
            )
        except (OSError, RuntimeError) as exc:
            logger.warning("截屏/分析异常: %s", exc)
            self._last_scene = SceneSummary(
                activity="unknown",
                pace="normal",
                event="normal",
                confidence=0.0,
                screen_context=screen_context_text,
            )

        cached = self._cache.get(self._last_scene, DEFAULT_AI_BARRAGE_COUNT)
        if len(cached) >= DEFAULT_AI_BARRAGE_COUNT and self._last_scene.event == "normal":
            self._buffer_items(cached)
            self._restart_capture_timer()
            logger.debug("使用缓存弹幕 | scene=%s/%s/%s", self._last_scene.activity, self._last_scene.pace, self._last_scene.event)
            return

        request = GenerationRequest(
            scene=self._last_scene,
            density=self._settings.density,
            personas=DEFAULT_PERSONAS,
            count=DEFAULT_AI_BARRAGE_COUNT,
            image_base64=encoded_frame,
        )

        # --- Log API request ON MAIN THREAD (before submit) ---
        api_provider = self._settings.api.provider if self._settings.api else "none"
        api_model = self._settings.api.model if self._settings.api else "none"
        ctx_preview = (request.scene.screen_context or "(无)")[:120]
        scene = request.scene
        self._panel.append_api_log(
            f">>> 发送请求: provider={api_provider} | model={api_model} | "
            f"scene={scene.activity}/{scene.pace}/{scene.event} | "
            f"image={'YES' if request.image_base64 else 'NO'}\n"
            f"    context: {ctx_preview}"
        )

        self._generation_future = self._executor.submit(self._generate_items, request)
        self._restart_capture_timer()

    def _generate_items(self, request: GenerationRequest) -> list[BarrageItem]:
        self._stats["api_calls"] += 1
        # Rough token estimate: CJK ~1.5 tokens/char, ASCII ~0.3 tokens/char
        text = (request.scene.screen_context or "") + " " * 200
        cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        ascii_chars = len(text) - cjk
        self._stats["tokens_approx_in"] += int(cjk * 1.5 + ascii_chars * 0.3)

        result = self._generator.generate(request)
        if result.error:
            logger.warning("[API 响应] 失败: %s", result.error)
            self._stats["api_failures"] += 1
            self._ai_failures += 1
            if self._ai_failures >= 3 and not isinstance(self._generator, MockBarrageService):
                logger.warning("AI 连续 %d 次失败，自动切换为模拟模式", self._ai_failures)
                self._generator = self._mock_generator
                self._panel.set_status("AI 请求连续失败，已切换模拟模式", "error")
        else:
            self._ai_failures = 0
            # Track token output
            total_text = "".join(item.text for item in result.items)
            cjk = sum(1 for c in total_text if "\u4e00" <= c <= "\u9fff")
            self._stats["tokens_approx_out"] += int(cjk * 1.5 + (len(total_text) - cjk) * 0.3)
            if result.source == "ai":
                self._stats["barrages_ai"] += len(result.items)
                self._last_api_response = "\n".join(item.text for item in result.items)
            elif result.source == "mock":
                self._stats["barrages_mock"] += len(result.items)
            elif result.source == "cache":
                self._stats["barrages_cache"] += len(result.items)
            # Log the response with actual barrage texts
            barrage_texts = " | ".join(item.text for item in result.items)
            logger.info(
                "[API 响应] source=%s | count=%d | barrages=[%s]",
                result.source, len(result.items), barrage_texts,
            )
        if result.items:
            self._cache.put(request.scene, result.items)
        return result.items

    def _render_tick(self) -> None:
        if self._overlay.barrage_region_height() <= 0:
            return

        if self._generation_future is not None and self._generation_future.done():
            try:
                items = self._generation_future.result()
                self._buffer_items(items)
            except Exception as exc:
                logger.error("生成任务异常: %s", exc)
            self._generation_future = None

        assignments = self._manager.tick(
            now=time.time(),
            viewport_width=max(1, self._overlay.width()),
            viewport_height=max(1, self._overlay.barrage_region_height()),
        )
        if assignments:
            self._overlay.render(assignments)

    def _send_interval_range(self) -> tuple[int, int]:
        """Return (min_ms, max_ms) based on density and highlight state."""
        is_highlight = self._last_scene.event == "highlight"
        table = DENSITY_HIGHLIGHT_INTERVAL if is_highlight else DENSITY_SEND_INTERVAL
        density = str(self._settings.density)
        result = table.get(density)
        if result is not None:
            return (int(result[0]), int(result[1]))
        return (400, 2000)

    def _schedule_next_send(self) -> None:
        if not self._paused:
            min_ms, max_ms = self._send_interval_range()
            delay = random.randint(min_ms, max_ms)
            self._send_timer.start(delay)

    def _send_next_barrage(self) -> None:
        if not self._paused and self._barrage_buffer:
            item = self._barrage_buffer.pop(0)
            self._apply_persona_speed(item)
            self._manager.enqueue([item])
            self._stats["barrages_sent"] += 1

        self._manager.set_burst(self._last_scene.event == "highlight")
        self._schedule_next_send()

    def _fill_buffer_tick(self) -> None:
        """Always runs — keeps the send buffer topped up via mock generation.
        AI-generated barrages (from the capture cycle) supplement this,
        but the mock fill ensures continuous flow regardless of API status."""
        if self._paused:
            return
        if len(self._barrage_buffer) >= 6:
            self._fill_timer.start(random.randint(400, 1000))
            return

        count = random.randint(1, 3)
        personas = random.sample(DEFAULT_PERSONAS, k=min(count, len(DEFAULT_PERSONAS)))
        request = GenerationRequest(
            scene=self._last_scene,
            density=self._settings.density,
            personas=personas,
            count=len(personas),
        )
        result = self._mock_generator.generate(request)
        if result.items:
            self._buffer_items(result.items)

        self._fill_timer.start(random.randint(400, 900))

    @staticmethod
    def _apply_persona_speed(item: BarrageItem) -> None:
        base = DEFAULT_BARRAGE_DURATION_SECONDS
        factor = PERSONA_SPEED.get(str(item.persona), 1.0)
        jitter = random.uniform(0.85, 1.15)
        item.duration_seconds = base * factor * jitter

    def _buffer_items(self, items: list[BarrageItem]) -> None:
        capacity = max(0, DEFAULT_BARRAGE_BUFFER_LIMIT - len(self._barrage_buffer))
        if capacity <= 0:
            logger.debug("发送缓冲区已满，丢弃 %d 条", len(items))
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
    setup_logging()

    # Fix: zh_MO locale has corrupted zeroDigit which breaks QSpinBox rendering.
    # Force C locale for consistent number formatting across all locales.
    from PySide6.QtCore import QLocale

    QLocale.setDefault(QLocale(QLocale.Language.C))

    app = QApplication(argv or sys.argv)
    settings_store = SettingsStore()
    settings, warning = settings_store.load()
    overlay = PySideOverlayRenderer()
    panel = ControlPanel(settings)
    tray = AppTray(panel)
    controller = RuntimeController(settings, settings_store, overlay, panel)
    panel.set_controller(controller)
    app.aboutToQuit.connect(controller.shutdown)

    if warning:
        logger.warning("配置加载警告: %s", warning)
        print(warning)

    tray.show()
    controller.start()
    return app.exec()
