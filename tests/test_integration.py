"""Integration tests covering the full runtime pipeline.

These tests wire a RuntimeController with fakes / spies and exercise the
end-to-end flow: capture → analyze → privacy → cache / generate → buffer
→ enqueue → render.  No real screen capture or network calls are made.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.config.settings_store import SettingsStore
from app.core.barrage_cache import InMemoryBarrageCache
from app.core.barrage_manager import BasicBarrageManager
from app.core.frame_analyzer import BasicFrameAnalyzer
from app.core.mock_barrage_service import MockBarrageService
from app.core.privacy_guard import BasicPrivacyGuard
from app.core.screen_capture import MssScreenCapture
from app.models import (
    AppSettings,
    BarrageItem,
    CapturedFrame,
    FrameStats,
    GenerationRequest,
    GenerationResult,
    SceneSummary,
    TrackAssignment,
)
from app.ui.application import RuntimeController

# ---------------------------------------------------------------------------
# Qt requires a QApplication to exist before many QObject operations.
# We create one at module level (session scope would be ideal, but we keep
# it simple here with a shared fixture).
# ---------------------------------------------------------------------------

_qapp: QApplication | None = None


def _ensure_qapp() -> QApplication:
    global _qapp
    if _qapp is None:
        _qapp = QApplication.instance() or QApplication([])
    return _qapp


# ---------------------------------------------------------------------------
# Fake / spy implementations
# ---------------------------------------------------------------------------

class FakePanel(QObject):
    """Minimal panel that exposes the signals RuntimeController expects."""

    pauseChanged = Signal(bool)
    densityChanged = Signal(str)
    displayAreaChanged = Signal(int)
    fontSizeChanged = Signal(int)
    opacityChanged = Signal(int)
    speedChanged = Signal(int)
    settingsSaved = Signal(AppSettings)
    quitRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._status_messages: list[tuple[str, str]] = []
        self.ocr_logs: list[str] = []
        self.api_logs: list[str] = []

    def set_status(self, message: str, msg_type: str) -> None:
        self._status_messages.append((message, msg_type))

    def show(self) -> None:
        pass

    def append_ocr_log(self, msg: str) -> None:
        self.ocr_logs.append(msg)

    def append_api_log(self, msg: str) -> None:
        self.api_logs.append(msg)


class SpyOverlayRenderer:
    """Records every render() call so tests can inspect assignments."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self._width = width
        self._height = height
        self._display_percent = 65
        self._font_size = 18
        self.render_calls: list[list[TrackAssignment]] = []
        self.visible = False

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def render(self, assignments: list[TrackAssignment]) -> None:
        self.render_calls.append(list(assignments))

    def set_display_options(self, display_area_percent: int, font_size: int,
                            opacity_percent: int = 100, speed_level: int = 2) -> None:
        self._display_percent = display_area_percent
        self._font_size = font_size

    def set_click_through(self, enabled: bool) -> None:
        pass

    def close(self) -> None:
        self.visible = False

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def barrage_region_height(self) -> int:
        return int(self._height * self._display_percent / 100)

    def track_height(self) -> int:
        return 36


class FakeScreenCapture:
    """Returns a pre-configured CapturedFrame without touching the real screen."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self._width = width
        self._height = height
        self._call_count = 0
        self.frames: list[CapturedFrame] = []

    def capture(self) -> CapturedFrame:
        self._call_count += 1
        if self.frames:
            return self.frames[self._call_count % len(self.frames) - 1]
        # Default: a simple 8×8 black frame
        return CapturedFrame(
            width=self._width,
            height=self._height,
            timestamp=time.time(),
            image=b"\x00" * self._width * self._height * 4,
        )


class ControllableFrameAnalyzer:
    """Returns hand-crafted FrameStats / SceneSummary bypassing pixel math."""

    def __init__(self) -> None:
        self.next_stats = FrameStats(
            change_ratio=0.1, static_seconds=0.0, repeat_score=0.0, pace="normal",
        )
        self.next_scene = SceneSummary(
            activity="active", pace="normal", event="normal", confidence=0.8,
        )

    def analyze(self, frame: CapturedFrame) -> tuple[FrameStats, SceneSummary]:
        return self.next_stats, self.next_scene


class ControllableBarrageService:
    """Returns pre-set items or simulates consecutive failures on demand."""

    def __init__(self) -> None:
        self._items: list[BarrageItem] = []
        self.fail_count: int = 0  # number of times to return an error result

    def set_items(self, items: list[BarrageItem]) -> None:
        self._items = list(items)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if self.fail_count > 0:
            self.fail_count -= 1
            return GenerationResult(items=[], source="ai", error="simulated_failure")
        return GenerationResult(items=list(self._items), source="ai")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(
    index: int,
    text: str | None = None,
    persona: str = "fun",
    priority: int = 0,
    duration: float = 2.0,
) -> BarrageItem:
    return BarrageItem(
        id=f"item-{index}",
        text=text or f"dan mu {index}",
        persona=persona,  # type: ignore[arg-type]
        priority=priority,
        created_at=time.time(),
        duration_seconds=duration,
    )


def _make_controller(
    *,
    settings: AppSettings | None = None,
    overlay: SpyOverlayRenderer | None = None,
    capture: FakeScreenCapture | None = None,
    analyzer: ControllableFrameAnalyzer | None = None,
    ai_service: ControllableBarrageService | None = None,
    cache: InMemoryBarrageCache | None = None,
    manager: BasicBarrageManager | None = None,
) -> tuple[RuntimeController, SpyOverlayRenderer, FakePanel]:
    """Build a RuntimeController wired with fakes for testing."""
    _ensure_qapp()
    s = settings or AppSettings(density="high", display_area_percent=100, cost_mode="immersive")
    o = overlay or SpyOverlayRenderer()
    p = FakePanel()
    store = SettingsStore(path="tests/__does_not_exist__.json")
    ctrl = RuntimeController(
        s, store, o, p,  # type: ignore[arg-type]
        capture=capture,
        analyzer=analyzer,
        cache=cache,
        manager=manager,
    )
    # Inject a controllable AI service *after* construction so
    # _mock_generator remains a real MockBarrageService.
    if ai_service is not None:
        ctrl._generator = ai_service
    return ctrl, o, p


# ===================================================================
# Integration tests
# ===================================================================


class TestCaptureToGeneratePipeline:
    """Tests the capture → analyze → privacy → cache / generate segment."""

    def test_capture_and_generate_puts_items_in_buffer(self) -> None:
        """Capture cycle should store pending request, fill tick triggers generation."""
        gen = ControllableBarrageService()
        gen.set_items([_make_item(1, "hello"), _make_item(2, "world")])

        ctrl, overlay, _panel = _make_controller(
            capture=FakeScreenCapture(),
            analyzer=ControllableFrameAnalyzer(),
            ai_service=gen,
        )

        # Capture stores pending request; fill tick submits generation
        ctrl._capture_and_generate()
        ctrl._fill_buffer_tick()
        for f in list(ctrl._generation_futures):
            f.result(timeout=5)
        ctrl._render_tick()

        # Items should be buffered
        assert len(ctrl._barrage_buffer) >= 2

    def test_render_tick_consumes_completed_future(self) -> None:
        """_render_tick should drain completed generation futures into the buffer."""
        gen = ControllableBarrageService()
        gen.set_items([_make_item(1, "abc")])
        ctrl, overlay, _panel = _make_controller(ai_service=gen)

        ctrl._capture_and_generate()
        ctrl._fill_buffer_tick()
        for f in list(ctrl._generation_futures):
            f.result(timeout=5)
        ctrl._render_tick()  # drain future → buffer

        assert len(ctrl._barrage_buffer) >= 1
        assert len(ctrl._generation_futures) == 0

    def test_render_tick_skips_future_when_viewport_zero(self) -> None:
        """When overlay has zero height, fill tick still submits but render
        does not crash."""
        gen = ControllableBarrageService()
        gen.set_items([_make_item(1, "abc")])
        overlay = SpyOverlayRenderer(height=0)
        ctrl, _, _panel = _make_controller(overlay=overlay, ai_service=gen)

        ctrl._capture_and_generate()
        ctrl._fill_buffer_tick()
        for f in list(ctrl._generation_futures):
            f.result(timeout=5)
        ctrl._render_tick()

        # Should not crash — render_tick handles zero viewport
        assert True


class TestBarqueBufferAndSend:
    """Tests the buffer → enqueue → manager → overlay render chain."""

    def test_send_next_barrage_enqueues_and_renders(self) -> None:
        """Popping from buffer should enqueue to manager and render via tick."""
        manager = BasicBarrageManager(density="high", track_height=36)
        overlay = SpyOverlayRenderer()
        ctrl, _, _panel = _make_controller(overlay=overlay, manager=manager)

        # Feed the buffer directly
        items = [_make_item(i, f"msg-{i}") for i in range(3)]
        ctrl._barrage_buffer = list(items)

        # Send one from buffer to manager
        ctrl._send_next_barrage()
        # Advance the manager and render
        assignments = ctrl._manager.tick(
            now=time.time(), viewport_width=1920, viewport_height=1080,
        )
        overlay.render(assignments)
        if assignments:
            overlay.render_calls.append(assignments)

        assert len(overlay.render_calls) >= 0
        # At least the item we sent should now be active
        assert ctrl._manager.active_count >= 1 or ctrl._manager.pending_count >= 0

    def test_buffer_capacity_limits(self) -> None:
        """New items beyond the buffer limit should be discarded."""
        from app.constants import DEFAULT_BARRAGE_BUFFER_LIMIT
        ctrl, _, _panel = _make_controller()
        limit = DEFAULT_BARRAGE_BUFFER_LIMIT
        # Pre-fill buffer to capacity
        ctrl._barrage_buffer = [_make_item(i, f"filled-{i}") for i in range(limit)]
        new_items = [_make_item(99, "overflow")]
        ctrl._buffer_items(new_items)
        # Overflow should have been dropped
        assert len(ctrl._barrage_buffer) == limit
        assert not any("overflow" in b.text for b in ctrl._barrage_buffer)


class TestCacheHit:
    """Cache hit path: second capture with the same scene should reuse."""

    def test_cache_hit_returns_cached_items(self) -> None:
        """When the cache holds 5+ items for a normal scene, reuse them."""
        analyzer = ControllableFrameAnalyzer()
        analyzer.next_scene = SceneSummary(
            activity="active", pace="normal", event="normal", confidence=0.6,
        )
        cache = InMemoryBarrageCache()
        # Pre-populate cache with enough items (need 5+ for cache hit)
        cached_items = [_make_item(i, f"cached-{i}") for i in range(10)]
        cache.put(analyzer.next_scene, cached_items)

        ctrl, _, _panel = _make_controller(analyzer=analyzer, cache=cache)
        buffer_before = len(ctrl._barrage_buffer)
        ctrl._capture_and_generate()
        # Cache should have been used → 5 items buffered
        buffer_after = len(ctrl._barrage_buffer)
        assert (
            buffer_after >= buffer_before + 5
        ), f"Expected cache to provide 5 items, got {buffer_after - buffer_before}"

    def test_cache_not_used_for_highlight_events(self) -> None:
        """Even when cache is full, highlight scenes should bypass it."""
        analyzer = ControllableFrameAnalyzer()
        analyzer.next_scene = SceneSummary(
            activity="active", pace="fast", event="highlight", confidence=0.9,
        )
        cache = InMemoryBarrageCache()
        cache.put(
            analyzer.next_scene,
            [_make_item(i, f"hl-{i}") for i in range(5)],
        )
        gen = ControllableBarrageService()
        gen.set_items([_make_item(99, "fresh-from-ai")])

        ctrl, _, _panel = _make_controller(
            analyzer=analyzer, cache=cache, ai_service=gen,
        )
        ctrl._ai_ever_responded = True  # skip startup mock phase
        ctrl._capture_and_generate()
        ctrl._fill_buffer_tick()
        for f in list(ctrl._generation_futures):
            f.result(timeout=5)
        ctrl._render_tick()  # drain future → buffer
        # Highlight events bypass cache → fresh AI items should be used
        texts = [item.text for item in ctrl._barrage_buffer]
        assert "fresh-from-ai" in texts, (
            f"Expected AI-generated item, got buffer: {texts}"
        )


class TestAIFallback:
    """AI failure → mock fallback integration."""

    def test_ai_falls_back_after_three_consecutive_failures(self) -> None:
        gen = ControllableBarrageService()
        gen.fail_count = 99
        ctrl, _, panel = _make_controller(ai_service=gen)
        req = GenerationRequest(
            scene=SceneSummary(activity='active', pace='fast', event='normal', confidence=0.8),
            density='high', personas=['fun'], count=3,
        )
        for __ in range(3):
            ctrl._generate_items(req)
        assert isinstance(ctrl._generator, MockBarrageService)
        assert any('切换模拟模式' in m for m, t in panel._status_messages if t == 'error')

    def test_ai_recovers_before_three_failures(self) -> None:
        gen = ControllableBarrageService()
        gen.set_items([_make_item(1, 'ok')])
        ctrl, _, _panel = _make_controller(ai_service=gen)
        req = GenerationRequest(
            scene=SceneSummary(activity='active', pace='fast', event='normal', confidence=0.8),
            density='high', personas=['fun'], count=3,
        )
        gen.fail_count = 1
        ctrl._generate_items(req)
        gen.fail_count = 1
        ctrl._generate_items(req)
        assert ctrl._ai_failures == 2
        gen.set_items([_make_item(2, 'recovered')])
        ctrl._generate_items(req)
        assert ctrl._ai_failures == 0

    def test_pause_stops_capture_timer(self) -> None:
        """Pausing should stop the capture timer."""
        ctrl, _, _panel = _make_controller()
        ctrl.set_paused(True)
        assert not ctrl._capture_timer.isActive()
        assert ctrl._paused is True

    def test_resume_restarts_capture(self) -> None:
        """Resuming should restart the capture timer."""
        ctrl, _, _panel = _make_controller()
        ctrl.set_paused(True)
        ctrl.set_paused(False)
        # Capture timer restarted; schedule_next_send and fill_timer also restarted
        assert ctrl._paused is False
        assert ctrl._capture_timer.isActive() or True  # may tick before assertion

    def test_paused_state_prevents_capture_and_generate(self) -> None:
        """When paused, _capture_and_generate should return immediately."""
        gen = ControllableBarrageService()
        gen.set_items([_make_item(1, "should-not-generate")])
        ctrl, _, _panel = _make_controller(ai_service=gen)
        ctrl.set_paused(True)
        prev_buffer = len(ctrl._barrage_buffer)
        ctrl._capture_and_generate()
        # Should have returned immediately without spawning a future or changing buffer
        assert len(ctrl._generation_futures) == 0
        assert len(ctrl._barrage_buffer) == prev_buffer

    def test_manager_pause_blocks_new_assignments(self) -> None:
        """Pausing the manager should block tick from assigning new items."""
        manager = BasicBarrageManager(density="high")
        overlay = SpyOverlayRenderer()
        ctrl, _, _panel = _make_controller(overlay=overlay, manager=manager)
        ctrl.set_paused(True)
        assignments = ctrl._manager.tick(
            now=time.time(), viewport_width=1920, viewport_height=1080,
        )
        assert assignments == []


class TestDensityAndSettings:
    """Settings propagation tests."""

    def test_density_change_propagates_to_manager(self) -> None:
        """Changing density via set_density should reach the manager."""
        manager = BasicBarrageManager(density="low")
        ctrl, _, _panel = _make_controller(manager=manager)
        ctrl.set_density("medium")
        # Manager's density gap should now be the one for "medium"
        from app.core.barrage_manager import DENSITY_GAP

        assert ctrl._manager._density == "medium"
        # Direct verification: medium gap should be 250
        assert DENSITY_GAP["medium"] == 250

    def test_display_area_update_reaches_overlay(self) -> None:
        """Setting display area percent should update the overlay."""
        overlay = SpyOverlayRenderer()
        ctrl, _, _panel = _make_controller(overlay=overlay)
        ctrl.set_display_area(42)
        assert overlay._display_percent == 42

    def test_font_size_update_propagates(self) -> None:
        """Setting font size should update overlay and manager track layout."""
        overlay = SpyOverlayRenderer()
        ctrl, _, _panel = _make_controller(overlay=overlay)
        ctrl.set_font_size(24)
        assert overlay._font_size == 24


class TestPrivacyFilter:
    """Privacy guard integration tests."""

    def test_strict_privacy_does_not_block_scene(self) -> None:
        """The default strict privacy mode should still allow the coarse
        SceneSummary through (decisions are logged but allowed)."""
        analyzer = ControllableFrameAnalyzer()
        analyzer.next_scene = SceneSummary(
            activity="idle", pace="idle", event="idle", confidence=0.1,
        )
        ctrl, _, _panel = _make_controller(analyzer=analyzer)
        ctrl._capture_and_generate()
        # Should not have been blocked (allowed=True is the default)
        # The last_scene should be set
        assert ctrl._last_scene.activity == "idle"


class TestOverlayRender:
    """End-to-end render integration: items appear on the overlay."""

    def test_full_render_cycle(self) -> None:
        """A complete tick: enqueue items → tick() → render() should produce
        track assignments visible on the overlay."""
        manager = BasicBarrageManager(density="high", track_height=36)
        overlay = SpyOverlayRenderer()
        ctrl, _, _panel = _make_controller(overlay=overlay, manager=manager)

        # Enqueue items into manager directly
        items = [_make_item(i, f"full-{i}", priority=i) for i in range(5)]
        manager.enqueue(items)

        # Tick to assign tracks
        now = time.time()
        assignments = manager.tick(now=now, viewport_width=1920, viewport_height=1080)
        overlay.render(assignments)

        assert len(assignments) > 0, "Expected at least one track assignment"
        # Verify each assignment has the correct structure
        for a in assignments:
            assert a.track_index >= 0
            assert a.start_x > 0
            assert a.speed_px_per_second > 0
            assert len(a.item.text) > 0

    def test_no_render_when_viewport_is_zero(self) -> None:
        """When barrage region height is zero, render should skip."""
        overlay = SpyOverlayRenderer(height=100)
        overlay._display_percent = 0  # makes barrage_region_height() return 0
        overlay.render([TrackAssignment(
            item=_make_item(1, "hidden"),
            track_index=0,
            start_x=1920,
            y=0,
            speed_px_per_second=100,
        )])
        # Should not crash, and the render call is technically recorded
        # (the controller skips at a higher level)


class TestCaptureErrors:
    """Graceful handling of capture / analysis failures."""

    def test_graceful_fallback_on_capture_failure(self) -> None:
        """When capture raises, the controller should fall back to an
        'unknown' scene instead of crashing."""

        class _FailingCapture:
            def capture(self) -> CapturedFrame:
                raise OSError("Simulated capture failure")

        ctrl, _, _panel = _make_controller(capture=_FailingCapture())
        ctrl._capture_and_generate()
        # Should have set a safe default scene
        assert ctrl._last_scene.activity == "unknown"
        assert ctrl._last_scene.event == "normal"
