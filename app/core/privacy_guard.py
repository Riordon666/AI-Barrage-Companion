"""Privacy filtering before context reaches generation services."""

from __future__ import annotations

from dataclasses import replace

from app.models import AppSettings, PrivacyDecision, SceneSummary


class BasicPrivacyGuard:
    """Keep outbound context limited to coarse scene metadata."""

    def sanitize(
        self,
        scene: SceneSummary,
        settings: AppSettings,
    ) -> PrivacyDecision:
        blocked_fields = ["screenshot"]

        if not settings.enable_ocr:
            blocked_fields.append("ocr_text")
        if not settings.enable_window_title:
            blocked_fields.append("window_title")
        if settings.privacy_mode == "strict":
            blocked_fields.extend(["file_name", "url", "chat_text"])

        sanitized_scene = replace(scene)
        reason = "Only coarse scene summary is allowed."

        return PrivacyDecision(
            allowed=True,
            sanitized_scene=sanitized_scene,
            blocked_fields=blocked_fields,
            reason=reason,
        )
