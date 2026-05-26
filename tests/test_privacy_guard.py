from app.core.privacy_guard import BasicPrivacyGuard
from app.models import AppSettings, SceneSummary


def test_strict_privacy_blocks_sensitive_context_fields() -> None:
    guard = BasicPrivacyGuard()
    scene = SceneSummary(
        activity="active",
        pace="fast",
        event="highlight",
        confidence=0.8,
    )

    decision = guard.sanitize(scene, AppSettings())

    assert decision.allowed is True
    assert decision.sanitized_scene == scene
    assert "screenshot" in decision.blocked_fields
    assert "ocr_text" in decision.blocked_fields
    assert "window_title" in decision.blocked_fields
    assert "file_name" in decision.blocked_fields
    assert "url" in decision.blocked_fields
    assert "chat_text" in decision.blocked_fields


def test_privacy_guard_clamps_scene_confidence() -> None:
    guard = BasicPrivacyGuard()
    scene = SceneSummary(
        activity="unknown",
        pace="normal",
        event="normal",
        confidence=1.5,
    )

    decision = guard.sanitize(scene, AppSettings())

    assert decision.sanitized_scene.confidence == 1.0


def test_balanced_privacy_respects_optional_context_flags() -> None:
    guard = BasicPrivacyGuard()
    scene = SceneSummary(
        activity="idle",
        pace="idle",
        event="idle",
        confidence=0.2,
    )
    settings = AppSettings(
        privacy_mode="balanced",
        enable_ocr=True,
        enable_window_title=True,
    )

    decision = guard.sanitize(scene, settings)

    assert decision.blocked_fields == ["screenshot"]
