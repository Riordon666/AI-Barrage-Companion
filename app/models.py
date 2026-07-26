"""Shared data models for AI Barrage Companion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Density = Literal["low", "medium", "high"]
CostMode = Literal["immersive", "balanced", "saving"]
PrivacyMode = Literal["strict", "balanced"]
Pace = Literal["idle", "slow", "normal", "fast"]
Activity = Literal["idle", "active", "repeated", "unknown"]
SceneEvent = Literal["normal", "highlight", "stuck", "idle"]
Persona = Literal["troll", "support", "sarcastic", "follower", "fun"]
GenerationSource = Literal["ai", "mock", "cache"]
CaptureReason = Literal["timer", "activity_change", "manual", "resume"]


@dataclass
class ApiConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0
    max_retries: int = 1
    protocol: str = "openai"  # "openai" | "anthropic"

    def __repr__(self) -> str:
        masked = self._mask_key(self.api_key)
        return (
            f"ApiConfig(provider={self.provider!r}, base_url={self.base_url!r}, "
            f"api_key={masked!r}, model={self.model!r}, "
            f"timeout_seconds={self.timeout_seconds}, max_retries={self.max_retries})"
        )

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) <= 8:
            return "***"
        return key[:4] + "****" + key[-4:]


@dataclass
class AppSettings:
    capture_interval_seconds: float = 4.0
    density: Density = "medium"
    cost_mode: CostMode = "balanced"
    api: ApiConfig | None = None
    api_history: list[ApiConfig] = field(default_factory=list)
    use_mock_when_api_missing: bool = True
    privacy_mode: PrivacyMode = "strict"
    enable_ocr: bool = False
    enable_window_title: bool = False
    enable_vision: bool = False
    display_area_percent: int = 60
    barrage_font_size: int = 24
    font_size_level: int = 2
    opacity_percent: int = 100
    speed_level: int = 2


@dataclass
class CapturedFrame:
    width: int
    height: int
    timestamp: float
    image: Any


@dataclass
class FrameStats:
    change_ratio: float
    static_seconds: float
    repeat_score: float
    pace: Pace


@dataclass
class SceneSummary:
    activity: Activity
    pace: Pace
    event: SceneEvent
    confidence: float
    screen_context: str = ""  # human-readable description e.g. "正在 VS Code 中编写代码"


@dataclass
class CapturePolicy:
    min_interval_seconds: float
    max_interval_seconds: float
    event_trigger_enabled: bool
    reason: CaptureReason


@dataclass
class PrivacyDecision:
    allowed: bool
    sanitized_scene: SceneSummary
    blocked_fields: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class BarrageItem:
    id: str
    text: str
    persona: Persona
    priority: int
    created_at: float
    duration_seconds: float


@dataclass
class GenerationRequest:
    scene: SceneSummary
    density: Density
    personas: list[Persona]
    count: int
    image_base64: str | None = None


@dataclass
class GenerationResult:
    items: list[BarrageItem]
    source: GenerationSource
    error: str | None = None
    # True when the items were already delivered incrementally through the
    # service's on_item callback while the response streamed in — the caller
    # must not buffer them a second time.
    streamed: bool = False


@dataclass
class TrackAssignment:
    item: BarrageItem
    track_index: int
    start_x: int
    y: int
    speed_px_per_second: float
