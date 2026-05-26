import pytest

from app.core.barrage_manager import BasicBarrageManager
from app.models import BarrageItem


def make_item(
    index: int,
    text: str | None = None,
    priority: int = 0,
    created_at: float | None = None,
    duration_seconds: float = 2.0,
) -> BarrageItem:
    return BarrageItem(
        id=f"item-{index}",
        text=text or f"弹幕{index}",
        persona="fun",
        priority=priority,
        created_at=index if created_at is None else created_at,
        duration_seconds=duration_seconds,
    )


def test_low_density_schedules_at_most_three_items() -> None:
    manager = BasicBarrageManager(density="low")
    manager.enqueue([make_item(index) for index in range(5)])

    assignments = manager.tick(now=0.0, viewport_width=800, viewport_height=600)

    assert len(assignments) == 3
    assert manager.active_count == 3
    assert manager.pending_count == 2
    assert [assignment.track_index for assignment in assignments] == [0, 1, 2]


def test_tracks_release_after_duration_and_pending_items_continue() -> None:
    manager = BasicBarrageManager(density="low")
    manager.enqueue([make_item(index, duration_seconds=1.0) for index in range(5)])

    first_batch = manager.tick(now=0.0, viewport_width=800, viewport_height=600)
    second_batch = manager.tick(now=1.1, viewport_width=800, viewport_height=600)

    assert len(first_batch) == 3
    assert len(second_batch) == 2
    assert manager.active_count == 2
    assert manager.pending_count == 0


def test_enqueue_deduplicates_pending_and_recent_text() -> None:
    manager = BasicBarrageManager(density="high")
    manager.enqueue([
        make_item(1, text="重复"),
        make_item(2, text="重复"),
        make_item(3, text="  重复  "),
    ])

    first_batch = manager.tick(now=0.0, viewport_width=800, viewport_height=600)
    manager.enqueue([make_item(4, text="重复")])
    second_batch = manager.tick(now=1.0, viewport_width=800, viewport_height=600)

    assert len(first_batch) == 1
    assert second_batch == []
    assert manager.pending_count == 0


def test_duplicate_text_can_return_after_duplicate_window_expires() -> None:
    manager = BasicBarrageManager(density="high", duplicate_window_seconds=1.0)
    manager.enqueue([make_item(1, text="回来", duration_seconds=0.5)])
    manager.tick(now=0.0, viewport_width=800, viewport_height=600)

    manager.tick(now=1.1, viewport_width=800, viewport_height=600)
    manager.enqueue([make_item(2, text="回来", duration_seconds=0.5)])
    second_batch = manager.tick(now=1.2, viewport_width=800, viewport_height=600)

    assert len(second_batch) == 1


def test_pause_blocks_new_assignments_until_resume() -> None:
    manager = BasicBarrageManager(density="medium")
    manager.enqueue([make_item(index) for index in range(3)])

    manager.pause()
    paused_batch = manager.tick(now=0.0, viewport_width=800, viewport_height=600)
    manager.resume()
    resumed_batch = manager.tick(now=0.1, viewport_width=800, viewport_height=600)

    assert paused_batch == []
    assert len(resumed_batch) == 3


def test_priority_items_are_scheduled_first() -> None:
    manager = BasicBarrageManager(density="medium")
    manager.enqueue([
        make_item(1, text="普通", priority=0, created_at=1.0),
        make_item(2, text="高能", priority=10, created_at=2.0),
    ])

    assignments = manager.tick(now=0.0, viewport_width=800, viewport_height=600)

    assert [assignment.item.text for assignment in assignments] == ["高能", "普通"]


def test_viewport_height_limits_track_capacity() -> None:
    manager = BasicBarrageManager(density="high")
    manager.enqueue([make_item(index) for index in range(5)])

    assignments = manager.tick(now=0.0, viewport_width=800, viewport_height=70)

    assert len(assignments) == 1
    assert assignments[0].track_index == 0


def test_invalid_density_raises_error() -> None:
    manager = BasicBarrageManager()

    with pytest.raises(ValueError):
        manager.set_density("extreme")
