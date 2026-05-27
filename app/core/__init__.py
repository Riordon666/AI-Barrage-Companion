"""Core business logic package."""

from app.core.ai_service import OpenAICompatibleBarrageService
from app.core.barrage_cache import InMemoryBarrageCache
from app.core.barrage_manager import BasicBarrageManager
from app.core.capture_scheduler import BasicCaptureScheduler
from app.core.frame_analyzer import BasicFrameAnalyzer
from app.core.mock_barrage_service import MockBarrageService
from app.core.ocr_engine import OcrCache, extract_screen_text
from app.core.privacy_guard import BasicPrivacyGuard
from app.core.screen_capture import MssScreenCapture
from app.core.screen_context import ScreenContext, capture_screen_context
from app.core.utils import (
    as_activity,
    as_capture_reason,
    as_density,
    as_persona,
    as_privacy_mode,
    as_scene_event,
    priority_for_event,
    raw_image_bytes,
)

__all__ = [
    # Service implementations
    "BasicBarrageManager",
    "BasicCaptureScheduler",
    "BasicFrameAnalyzer",
    "BasicPrivacyGuard",
    "InMemoryBarrageCache",
    "MockBarrageService",
    "MssScreenCapture",
    "OpenAICompatibleBarrageService",
    # Screen context & OCR
    "capture_screen_context",
    "extract_screen_text",
    "OcrCache",
    "ScreenContext",
    # Shared utilities
    "as_activity",
    "as_capture_reason",
    "as_density",
    "as_persona",
    "as_privacy_mode",
    "as_scene_event",
    "priority_for_event",
    "raw_image_bytes",
]
