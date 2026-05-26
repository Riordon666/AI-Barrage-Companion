"""Privacy filtering before scene context reaches any generator."""

from __future__ import annotations

from app.models import AppSettings, PrivacyDecision, SceneSummary


STRICT_BLOCKED_FIELDS = [
    "screenshot",
    "ocr_text",
    "window_title",
    "file_name",
    "url",
    "chat_text",
]


class BasicPrivacyGuard:
    """Allow only the coarse SceneSummary fields used by MVP generation."""

    def sanitize(
        self,
        scene: SceneSummary,
        settings: AppSettings,
    ) -> PrivacyDecision:
        blocked_fields: list[str] = ["screenshot"]

        if settings.privacy_mode == "strict":
            blocked_fields = STRICT_BLOCKED_FIELDS.copy()
        else:
            if not settings.enable_ocr:
                blocked_fields.append("ocr_text")
            if not settings.enable_window_title:
                blocked_fields.append("window_title")

        return PrivacyDecision(
            allowed=True,
            sanitized_scene=SceneSummary(
                activity=scene.activity,
                pace=scene.pace,
                event=scene.event,
                confidence=max(0.0, min(scene.confidence, 1.0)),
            ),
            blocked_fields=blocked_fields,
            reason=None,
        )
