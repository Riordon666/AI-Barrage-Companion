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
    timeout_seconds: float = 20.0
    max_retries: int = 1


@dataclass
class AppSettings:
    capture_interval_seconds: float = 4.0
    density: Density = "medium"
    cost_mode: CostMode = "balanced"
    api: ApiConfig | None = None
    use_mock_when_api_missing: bool = True
    privacy_mode: PrivacyMode = "strict"
    enable_ocr: bool = False
    enable_window_title: bool = False
    display_area_percent: int = 65
    barrage_font_size: int = 18


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


@dataclass
class GenerationResult:
    items: list[BarrageItem]
    source: GenerationSource
    error: str | None = None


@dataclass
class TrackAssignment:
    item: BarrageItem
    track_index: int
    start_x: int
    y: int
    speed_px_per_second: float
