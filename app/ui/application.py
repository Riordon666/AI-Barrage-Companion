"""PySide application wiring for the MVP runtime."""

from __future__ import annotations

import queue
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
from app.core.ocr_engine import OcrCache, extract_screen_text_with_status
from app.core.privacy_guard import BasicPrivacyGuard
from app.core.screen_capture import MssScreenCapture
from app.core.screen_context import capture_screen_context
from app.core.utils import as_density
from app.models import AppSettings, BarrageItem, CapturedFrame, Density, FrameStats, GenerationRequest, SceneSummary
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
        self._uses_default_capture = capture is None
        self._capture = capture or MssScreenCapture()
        self._analyzer = analyzer or BasicFrameAnalyzer()
        self._capture_scheduler = capture_scheduler or BasicCaptureScheduler()
        self._privacy_guard = privacy_guard or BasicPrivacyGuard()
        self._mock_generator = mock_generator or MockBarrageService()
        # Streamed barrages land here from worker threads the moment their
        # line arrives; the render tick drains it on the main thread. Must
        # exist before _build_generator wires the on_item callback to it.
        self._stream_queue: queue.SimpleQueue[BarrageItem] = queue.SimpleQueue()
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
        self._executor = ThreadPoolExecutor(max_workers=6)
        self._generation_futures: list[Future[list[BarrageItem]]] = []
        self._barrage_buffer: list[BarrageItem] = []
        self._ai_buf_count: int = 0  # tracks AI barrages only (mock excluded)
        self._api_latency_ms: float = 0
        self._concurrent_count: int = 0
        self._latency_ema_s: float = 6.0  # EMA estimate, seeded at 6s (medium)
        self._pending_request: GenerationRequest | None = None
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
        self._ocr_accumulator: list[str] = []
        self._ai_ever_responded: bool = False  # becomes True on first AI success
        self._last_api_request: str = ""
        self._last_api_response: str = ""
        self._ocr_future: Future | None = None  # async OCR task

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
        panel.opacityChanged.connect(self.set_opacity)
        panel.speedChanged.connect(self.set_speed)
        panel.settingsSaved.connect(self.update_settings)
        panel.quitRequested.connect(QApplication.quit)

    def start(self) -> None:
        self._overlay.show()
        self._panel.show()
        self._render_timer.start(DEFAULT_RENDER_TICK_MS)
        self._schedule_next_send()
        self._fill_timer.start(random.randint(400, 900))

        # Startup warmup: inject welcome mock barrages immediately
        if not isinstance(self._generator, MockBarrageService):
            warmup_texts = [
                "开播了！", "来了来了", "主播今天好早", "终于等到你",
                "前排前排", "今天播什么", "好久不见", "欢迎欢迎",
                "我最爱的主播又开播了", "第一！", "蹲到了", "来晚了没有",
                "终于开播了！", "我来晚了吗？ ", "gogogo出发咯", "主播你干嘛哈哈哎哟",
                "鸡你太美", "主播这期是不是有点太隐晦了",
            ]
            from app.models import BarrageItem as BI
            import uuid
            warmup_items = [
                BI(id=str(uuid.uuid4()), text=t, persona=random.choice(DEFAULT_PERSONAS),
                   priority=0, created_at=time.time(), duration_seconds=8.0)
                for t in random.sample(warmup_texts, k=min(20, len(warmup_texts)))
            ]
            self._buffer_items(warmup_items, source="mock")
            self._stats["barrages_mock"] += len(warmup_items)
            logger.info("启动预热: 已注入 %d 条模拟欢迎弹幕", len(warmup_items))

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
                result = extract_screen_text_with_status(frame)
                if result.text:
                    self._panel.append_ocr_log(
                        f"OCR 自检通过: {result.engine} 识别到 {len(result.text)} 字符"
                    )
                else:
                    self._panel.append_ocr_log(
                        f"OCR 自检: {result.message}"
                    )
            except Exception:
                pass  # self-test is non-critical

    def shutdown(self) -> None:
        self._ocr_future = None
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
    def api_latency_ms(self) -> float:
        return self._api_latency_ms

    @property
    def concurrent_count(self) -> int:
        return self._concurrent_count

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
        self._overlay.set_display_options(value, self._settings.barrage_font_size,
                                          self._settings.opacity_percent,
                                          self._settings.speed_level)

    def set_font_size(self, value: int) -> None:
        self._settings.barrage_font_size = value
        self._overlay.set_display_options(self._settings.display_area_percent, value,
                                          self._settings.opacity_percent,
                                          self._settings.speed_level)
        self._manager.set_track_layout(self._overlay.track_height(), DEFAULT_TRACK_GAP)

    def set_opacity(self, value: int) -> None:
        self._settings.opacity_percent = value
        self._overlay.set_opacity(value)

    def set_speed(self, value: int) -> None:
        self._settings.speed_level = value
        self._overlay.set_speed(value)

    def update_settings(self, settings: AppSettings) -> None:
        self._settings = settings
        self._manager.set_density(settings.density)
        self._overlay.set_display_options(settings.display_area_percent, settings.barrage_font_size,
                                          settings.opacity_percent, settings.speed_level)
        self._manager.set_track_layout(self._overlay.track_height(), DEFAULT_TRACK_GAP)
        self._generator = self._build_generator()
        self._ai_failures = 0  # reset on settings change
        self._restart_capture_timer()
        self._fill_timer.start(random.randint(400, 900))
        source = "模拟弹幕" if isinstance(self._generator, MockBarrageService) else "AI"
        logger.info(
            "配置已更新 | 来源=%s | 密度=%s | 成本=%s | 隐私=%s | "
            "截屏间隔=%.1fs | 显示区域=%d%% | 不透明度=%d%% | 速度=%d",
            source, settings.density, settings.cost_mode, settings.privacy_mode,
            settings.capture_interval_seconds, settings.display_area_percent,
            settings.opacity_percent, settings.speed_level,
        )

    def _capture_and_generate(self) -> None:
        if self._paused:
            return

        # Collect completed futures first
        for f in list(self._generation_futures):
            if f.done():
                try:
                    items = f.result()
                    self._buffer_items(items)
                    self._feed_activity(items)
                except Exception:
                    pass
                self._generation_futures.remove(f)

        self._stats["captures"] += 1
        encoded_frame: str | None = None
        screen_context_text = ""

        try:
            frame = self._capture.capture()
        except Exception as exc:
            if not self._uses_default_capture:
                logger.warning("截屏异常，使用安全默认场景: %s", exc)
                self._last_scene = SceneSummary(
                    activity="unknown",
                    pace="normal",
                    event="normal",
                    confidence=0.0,
                    screen_context="",
                )
                self._restart_capture_timer()
                return
            logger.warning("截屏异常，使用空帧继续流程: %s", exc)
            frame = self._blank_frame()

        try:
            # --- OCR: submit to background thread, use accumulated results ---
            ocr_text = " | ".join(self._ocr_accumulator[-10:]) if self._ocr_accumulator else self._last_ocr_text
            if self._settings.enable_ocr and not isinstance(self._generator, MockBarrageService):
                if self._ocr_future is None or self._ocr_future.done():
                    self._ocr_future = self._executor.submit(
                        extract_screen_text_with_status, frame
                    )
                # else: previous OCR still running, skip this cycle
            # -----------------------------------------------------

            # --- Window title context ---
            if self._settings.enable_window_title:
                ctx = capture_screen_context()
                if ctx.is_meaningful:
                    screen_context_text = ctx.description
                    logger.info("屏幕上下文: %s (%s)", ctx.description, ctx.app_category)

            if (
                self._settings.enable_vision
                and not isinstance(self._generator, MockBarrageService)
                and not self._vision_known_unsupported()
            ):
                encoded_frame = encode_frame_jpeg_base64(frame)

            # Compress frame for fast analysis (max 800px)
            analysis_frame = self._shrink_frame(frame, max_dim=800)
            self._last_stats, scene = self._analyzer.analyze(analysis_frame)

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
        except Exception as exc:
            logger.warning("截屏/分析异常: %s", exc)
            self._last_scene = SceneSummary(
                activity="unknown",
                pace="normal",
                event="normal",
                confidence=0.0,
                screen_context=screen_context_text,
            )

        cached = self._cache.get(self._last_scene, DEFAULT_AI_BARRAGE_COUNT)
        if len(cached) >= 5 and self._last_scene.event == "normal":
            take = min(len(cached), 5)
            self._buffer_items(cached[:take])
            self._stats["barrages_cache"] += take
            self._restart_capture_timer()
            logger.debug("使用缓存弹幕 %d 条 | scene=%s/%s/%s", take, self._last_scene.activity, self._last_scene.pace, self._last_scene.event)
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
        # Store latest scene for fill timer to trigger generation
        self._pending_request = request
        # Clear OCR accumulator — these texts have been included in the request
        self._ocr_accumulator.clear()
        self._restart_capture_timer()

    def _generate_items(self, request: GenerationRequest) -> list[BarrageItem]:
        self._concurrent_count += 1
        self._stats["api_calls"] += 1
        t0 = time.time()
        # Rough token estimate: CJK ~1.5 tokens/char, ASCII ~0.3 tokens/char
        text = (request.scene.screen_context or "") + " " * 200
        cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        ascii_chars = len(text) - cjk
        self._stats["tokens_approx_in"] += int(cjk * 1.5 + ascii_chars * 0.3)

        result = self._generator.generate(request)
        elapsed_s = time.time() - t0
        self._api_latency_ms = elapsed_s * 1000
        # EMA smoothing: α=0.3, so recent responses have more weight
        self._latency_ema_s = 0.3 * elapsed_s + 0.7 * self._latency_ema_s
        self._concurrent_count = max(0, self._concurrent_count - 1)

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
            if not self._ai_ever_responded:
                self._ai_ever_responded = True
                logger.info("首次 AI 响应到达 (延迟≈%.1fs)，切换为 AI+模拟混合模式", self._latency_ema_s)
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
        if result.streamed:
            # Items already reached the buffer one by one through the stream
            # queue while the response was still in flight.
            return []
        return result.items

    def _render_tick(self) -> None:
        self._drain_stream_queue()
        if self._overlay.barrage_region_height() <= 0:
            return

        # --- Check async OCR result ---
        if self._ocr_future is not None and self._ocr_future.done():
            try:
                ocr_result = self._ocr_future.result()
                raw_text = ocr_result.text
                if raw_text and self._ocr_cache.should_send(raw_text):
                    self._last_ocr_text = raw_text
                    self._ocr_accumulator.append(raw_text)
                    if len(self._ocr_accumulator) > 20:
                        self._ocr_accumulator = self._ocr_accumulator[-20:]
                    self._panel.append_ocr_log(
                        f"{ocr_result.engine} 识别到 {len(raw_text)} 字符，已累积 {len(self._ocr_accumulator)} 条"
                    )
                    logger.info("OCR 识别 %d 字符（累积 %d 条）: %.80s", len(raw_text), len(self._ocr_accumulator), raw_text)
                elif raw_text:
                    self._panel.append_ocr_log(
                        f"识别到 {len(raw_text)} 字符，重复内容已抑制:\n{raw_text[:120]}"
                    )
                else:
                    self._panel.append_ocr_log(f"OCR 扫描完成：{ocr_result.message}")
            except Exception as exc:
                logger.warning("OCR 后台任务异常: %s", exc)
            self._ocr_future = None

        # Collect completed generation futures
        for f in list(self._generation_futures):
            if f.done():
                try:
                    items = f.result()
                    self._buffer_items(items)
                    self._feed_activity(items)
                except Exception:
                    pass
                self._generation_futures.remove(f)

        assignments = self._manager.tick(
            now=time.time(),
            viewport_width=max(1, self._overlay.width()),
            viewport_height=max(1, self._overlay.barrage_region_height()),
        )
        if assignments:
            self._overlay.render(assignments)

    def _send_interval_range(self) -> tuple[int, int]:
        """Return (min_ms, max_ms) based on density and highlight state.
        Adds backpressure when buffer is very full to spread out batches."""
        is_highlight = self._last_scene.event == "highlight"
        table = DENSITY_HIGHLIGHT_INTERVAL if is_highlight else DENSITY_SEND_INTERVAL
        density = str(self._settings.density)
        result = table.get(density)
        if result is None:
            result = (400, 2000)
        min_ms, max_ms = int(result[0]), int(result[1])
        # Backpressure: when buffer is full, slow down to avoid dumping all at once
        buf_len = len(self._barrage_buffer)
        if buf_len > 25:
            factor = min(4.0, buf_len / 15.0)
            min_ms = int(min_ms * factor)
            max_ms = int(max_ms * factor)
        return (min_ms, max_ms)

    def _schedule_next_send(self) -> None:
        if not self._paused:
            min_ms, max_ms = self._send_interval_range()
            delay = random.randint(min_ms, max_ms)
            self._send_timer.start(delay)

    def _send_next_barrage(self) -> None:
        if not self._paused and self._barrage_buffer:
            item = self._barrage_buffer.pop(0)
            self._ai_buf_count = max(0, self._ai_buf_count - 1)
            self._apply_persona_speed(item)
            self._manager.enqueue([item])
            self._stats["barrages_sent"] += 1

        self._manager.set_burst(self._last_scene.event == "highlight")
        self._schedule_next_send()

    def _fill_buffer_tick(self) -> None:
        """Dynamic concurrency: more concurrent AI requests when buffer is low,
        fewer when buffer is high. Mock blended per cost mode."""
        if self._paused:
            return

        use_ai = not isinstance(self._generator, MockBarrageService)
        buf_len = len(self._barrage_buffer)
        ai_cnt = self._ai_buf_count  # only AI barrages, for trigger decisions

        # Clean up completed futures
        self._generation_futures = [f for f in self._generation_futures if not f.done()]

        if not use_ai:
            if buf_len < 6:
                count = random.randint(1, 3)
                personas = random.sample(DEFAULT_PERSONAS, k=min(count, len(DEFAULT_PERSONAS)))
                result = self._mock_generator.generate(GenerationRequest(
                    scene=self._last_scene, density=self._settings.density,
                    personas=personas, count=len(personas),
                ))
                if result.items:
                    self._buffer_items(result.items, source="mock")
                    self._stats["barrages_mock"] += len(result.items)
            self._fill_timer.start(random.randint(400, 900))
            return

        # AI mode: adaptive batching + startup phase handling
        in_flight = len(self._generation_futures)
        cost = str(self._settings.cost_mode)
        density = str(self._settings.density)
        lat = self._latency_ema_s

        # ── Startup: more aggressive mock while waiting for first AI ─────
        if not self._ai_ever_responded:
            if buf_len < 50:
                count = random.randint(2, 4)
                personas = random.sample(DEFAULT_PERSONAS, k=min(count, len(DEFAULT_PERSONAS)))
                result = self._mock_generator.generate(GenerationRequest(
                    scene=self._last_scene, density=density,
                    personas=personas, count=len(personas),
                ))
                if result.items:
                    self._buffer_items(result.items, source="mock")
                    self._stats["barrages_mock"] += len(result.items)
        # ──────────────────────────────────────────────────────────────────

        # Adaptive batch size: scales from 8 (fast) → 50 (very slow)
        adaptive_batch = max(8, min(50, int(lat * 1.3 + 3)))
        scale = 1.5 if density == "high" else 1.0
        thresholds = {
            "empty": int(adaptive_batch * 0.5 * scale),
            "low":   int(adaptive_batch * 1.1 * scale),
            "mid":   int(adaptive_batch * 1.8 * scale),
        }

        # Use AI-only count for trigger decisions (mock doesn't count)
        if ai_cnt < thresholds["empty"]:
            level = "empty"
        elif ai_cnt < thresholds["low"]:
            level = "low"
        elif ai_cnt < thresholds["mid"]:
            level = "mid"
        else:
            level = "full"

        # Adaptive concurrency
        if lat < 3.0:
            concurrency = {"empty": 1, "low": 1, "mid": 1, "full": 0}
        elif lat < 8.0:
            concurrency = {"empty": 2, "low": 1, "mid": 1, "full": 0}
        elif lat < 20.0:
            concurrency = {"empty": 3, "low": 2, "mid": 1, "full": 0}
        else:
            concurrency = {"empty": 4, "low": 3, "mid": 2, "full": 1}

        cost_scale = {"immersive": 1.0, "balanced": 0.6, "saving": 0.3}
        cs = cost_scale.get(cost, 1.0)
        target = max(0, int(concurrency.get(level, 0) * cs + 0.5))

        # Mock blend — inject mock barrages ALONGSIDE AI every tick
        mock_per_tick = {"immersive": 1, "balanced": 2, "saving": 4}
        mock_n = random.randint(0, mock_per_tick.get(cost, 2))
        if mock_n > 0 and buf_len < 100:
            personas = random.sample(DEFAULT_PERSONAS, k=min(mock_n, len(DEFAULT_PERSONAS)))
            result = self._mock_generator.generate(GenerationRequest(
                scene=self._last_scene, density=density,
                personas=personas, count=len(personas),
            ))
            if result.items:
                self._buffer_items(result.items, source="mock")
                self._stats["barrages_mock"] += len(result.items)

        # Launch AI requests up to target concurrency
        launched = 0
        while in_flight + launched < target and self._pending_request is not None:
            # Override batch size in the pending request with adaptive value
            self._pending_request.count = adaptive_batch
            logger.info(
                "AI请求 | 批次=%d条 | 并发=%d/%d | 缓冲=%d | 延迟≈%.1fs",
                adaptive_batch, in_flight + launched + 1, target, buf_len, lat,
            )
            fut = self._executor.submit(self._generate_items, self._pending_request)
            self._generation_futures.append(fut)
            launched += 1

        # Faster tick during startup to keep mock flowing
        interval = random.randint(300, 600) if not self._ai_ever_responded else random.randint(800, 2500)
        self._fill_timer.start(interval)

    def _drain_stream_queue(self) -> None:
        """Move barrages streamed by worker threads into the send buffer."""
        drained: list[BarrageItem] = []
        try:
            while True:
                drained.append(self._stream_queue.get_nowait())
        except queue.Empty:
            pass
        if not drained:
            return
        if not self._ai_ever_responded:
            # Flip the startup flag on the FIRST streamed barrage, not on
            # batch completion — this is what ends the mock-heavy warmup.
            self._ai_ever_responded = True
            logger.info("首条 AI 弹幕已到达（流式），切换为 AI+模拟混合模式")
        self._buffer_items(drained, source="ai")

    def _feed_activity(self, items: list[BarrageItem]) -> None:
        """Send AI-generated barrages to the activity panel for display."""
        ai_items = [
            (item.persona, item.text)
            for item in items
            if item.persona and item.text
        ]
        if ai_items:
            self._panel.add_activity_items(ai_items)

    @staticmethod
    def _apply_persona_speed(item: BarrageItem) -> None:
        base = DEFAULT_BARRAGE_DURATION_SECONDS
        factor = PERSONA_SPEED.get(str(item.persona), 1.0)
        jitter = random.uniform(0.95, 1.05)
        item.duration_seconds = base * factor * jitter

    def _buffer_items(self, items: list[BarrageItem], source: str = "ai") -> None:
        capacity = max(0, DEFAULT_BARRAGE_BUFFER_LIMIT - len(self._barrage_buffer))
        if capacity <= 0:
            logger.debug("发送缓冲区已满，丢弃 %d 条", len(items))
            return
        added = items[:capacity]
        self._barrage_buffer.extend(added)
        if source == "ai":
            self._ai_buf_count += len(added)

    def _vision_known_unsupported(self) -> bool:
        """True when this (base_url, model) already rejected an image request.

        Saves a JPEG encode per capture cycle — and the doomed 400 round-trip
        — once the provider has told us it can't take images (e.g. DeepSeek).
        """
        api = self._settings.api
        if api is None:
            return False
        return (api.base_url, api.model) in OpenAICompatibleBarrageService._vision_disabled

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
            on_item=self._stream_queue.put,
        )

    @staticmethod
    def _shrink_frame(frame: CapturedFrame, max_dim: int = 800) -> CapturedFrame:
        """Return a copy of *frame* with its image downscaled so the longest
        side does not exceed *max_dim*. Uses Pillow for fast resampling."""
        w, h = frame.width, frame.height
        if max(w, h) <= max_dim:
            return frame
        from PIL import Image
        raw = getattr(frame, 'raw', None) or getattr(frame, 'bgra', None) or getattr(frame, 'rgb', None) or getattr(frame.image, 'raw', None)
        if raw is None:
            raw = bytes(frame.image) if hasattr(frame.image, '__bytes__') else b''
        bpp = max(1, len(raw) // max(1, w * h))
        mode = 'RGBA' if bpp >= 4 else 'RGB' if bpp >= 3 else 'L'
        try:
            img = Image.frombuffer(mode, (w, h), raw, 'raw', mode)
        except Exception:
            img = Image.frombytes(mode, (w, h), raw)
        scale = max_dim / max(w, h)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        raw_out = img.tobytes('raw', mode)
        return CapturedFrame(
            width=new_size[0], height=new_size[1],
            timestamp=frame.timestamp, image=raw_out,
        )

    @staticmethod
    def _blank_frame() -> CapturedFrame:
        from app.models import CapturedFrame

        width = 8
        height = 8
        return CapturedFrame(
            width=width,
            height=height,
            timestamp=time.time(),
            image=b"\x00" * width * height * 4,
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
    panel = ControlPanel(settings, settings_store)
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
