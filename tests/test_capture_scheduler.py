from app.core.capture_scheduler import BasicCaptureScheduler
from app.models import AppSettings, FrameStats


def test_scheduler_respects_user_interval() -> None:
    settings = AppSettings(cost_mode="saving", capture_interval_seconds=4.0)

    policy = BasicCaptureScheduler().next_policy(None, settings)

    assert policy.min_interval_seconds == 4.0
    assert policy.max_interval_seconds == 4.0


def test_scheduler_speeds_up_fast_activity() -> None:
    settings = AppSettings(capture_interval_seconds=4.0)
    stats = FrameStats(
        change_ratio=0.5,
        static_seconds=0.0,
        repeat_score=0.1,
        pace="fast",
    )

    policy = BasicCaptureScheduler().next_policy(stats, settings)

    assert policy.min_interval_seconds == 1.0
    assert policy.reason == "activity_change"
