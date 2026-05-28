"""Capture interval policy."""

from __future__ import annotations

from app.core.utils import as_capture_reason
from app.models import AppSettings, CapturePolicy, CaptureReason, FrameStats


class BasicCaptureScheduler:
    """Choose a simple timer interval from settings and recent activity."""

    def next_policy(
        self,
        last_stats: FrameStats | None,
        settings: AppSettings,
    ) -> CapturePolicy:
        base = max(0.5, settings.capture_interval_seconds)
        min_interval = base
        max_interval = base
        reason = "timer"

        if last_stats is not None:
            if last_stats.pace == "idle":
                max_interval = max(max_interval, 12.0)
            elif last_stats.pace == "fast":
                min_interval = min(min_interval, 1.0)
                reason = "activity_change"

        return CapturePolicy(
            min_interval_seconds=min_interval,
            max_interval_seconds=max_interval,
            event_trigger_enabled=True,
            reason=as_capture_reason(reason),
        )
