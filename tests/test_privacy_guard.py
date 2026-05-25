from app.core.privacy_guard import BasicPrivacyGuard
from app.models import AppSettings, SceneSummary


def test_privacy_guard_blocks_sensitive_fields_by_default() -> None:
    scene = SceneSummary(
        activity="active",
        pace="normal",
        event="normal",
        confidence=0.8,
    )

    decision = BasicPrivacyGuard().sanitize(scene, AppSettings())

    assert decision.allowed is True
    assert decision.sanitized_scene == scene
    assert "screenshot" in decision.blocked_fields
    assert "ocr_text" in decision.blocked_fields
    assert "window_title" in decision.blocked_fields
    assert "file_name" in decision.blocked_fields
    assert "url" in decision.blocked_fields
    assert "chat_text" in decision.blocked_fields


def test_privacy_guard_respects_explicit_context_toggles() -> None:
    scene = SceneSummary(
        activity="active",
        pace="fast",
        event="highlight",
        confidence=0.9,
    )
    settings = AppSettings(
        privacy_mode="balanced",
        enable_ocr=True,
        enable_window_title=True,
    )

    decision = BasicPrivacyGuard().sanitize(scene, settings)

    assert decision.blocked_fields == ["screenshot"]
