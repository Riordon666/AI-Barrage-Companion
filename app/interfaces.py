"""Core protocols used to keep ABC modules decoupled."""

from __future__ import annotations

from typing import Protocol

from app.models import (
    AppSettings,
    BarrageItem,
    CapturePolicy,
    CapturedFrame,
    FrameStats,
    GenerationRequest,
    GenerationResult,
    PrivacyDecision,
    SceneSummary,
    TrackAssignment,
)


class ScreenCapture(Protocol):
    def capture(self) -> CapturedFrame:
        """Capture the current screen for local analysis."""


class FrameAnalyzer(Protocol):
    def analyze(self, frame: CapturedFrame) -> tuple[FrameStats, SceneSummary]:
        """Convert a captured frame into lightweight local scene signals."""


class CaptureScheduler(Protocol):
    def next_policy(
        self,
        last_stats: FrameStats | None,
        settings: AppSettings,
    ) -> CapturePolicy:
        """Choose when and why the next capture should happen."""


class PrivacyGuard(Protocol):
    def sanitize(
        self,
        scene: SceneSummary,
        settings: AppSettings,
    ) -> PrivacyDecision:
        """Filter context before anything is sent to an AI service."""


class BarrageGenerator(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate barrage items from a scene summary."""


class BarrageCache(Protocol):
    def get(self, scene: SceneSummary, count: int) -> list[BarrageItem]:
        """Return cached barrage items for similar scenes."""

    def put(self, scene: SceneSummary, items: list[BarrageItem]) -> None:
        """Store barrage items for later reuse."""


class BarrageManager(Protocol):
    def enqueue(self, items: list[BarrageItem]) -> None:
        """Queue barrage items for display."""

    def tick(
        self,
        now: float,
        viewport_width: int,
        viewport_height: int,
    ) -> list[TrackAssignment]:
        """Advance scheduling and return items ready for rendering."""

    def set_density(self, density: str) -> None:
        """Change the display density."""

    def pause(self) -> None:
        """Pause barrage scheduling."""

    def resume(self) -> None:
        """Resume barrage scheduling."""


class OverlayRenderer(Protocol):
    def show(self) -> None:
        """Show the overlay window."""

    def hide(self) -> None:
        """Hide the overlay window."""

    def render(self, assignments: list[TrackAssignment]) -> None:
        """Render assigned barrage items."""

    def set_click_through(self, enabled: bool) -> None:
        """Enable or disable click-through behavior."""

    def close(self) -> None:
        """Close the overlay window."""
