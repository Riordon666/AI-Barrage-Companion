import pytest

from app.core.barrage_manager import DENSITY_GAP, BasicBarrageManager
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
        text=text or f"dan mu {index}",
        persona="fun",
        priority=priority,
        created_at=index if created_at is None else created_at,
        duration_seconds=duration_seconds,
    )


def test_all_tracks_eligible_on_first_tick() -> None:
    """Every track is free when nothing is scrolling."""
    manager = BasicBarrageManager(density="low")
    manager.enqueue([make_item(i) for i in range(8)])

    assignments = manager.tick(now=0.0, viewport_width=800, viewport_height=600)

    # 600 / (36+12) ≈ 12 tracks, all free → 8 items assigned
    assert len(assignments) == 8
    assert manager.active_count == 8
    assert manager.pending_count == 0


def test_same_track_blocked_until_gap_elapsed() -> None:
    """A track is blocked for a new barrage until the previous one has
    scrolled past the density gap."""
    # Use a low viewport so only 1 track exists.
    manager = BasicBarrageManager(density="low")
    manager.enqueue([make_item(i) for i in range(3)])

    # First tick: 1 track, 1 assigned
    first = manager.tick(now=0.0, viewport_width=800, viewport_height=40)
    assert len(first) == 1
    assert manager.active_count == 1

    # Same tick (same now): track still has a fresh barrage, gap not met.
    nothing = manager.tick(now=0.0, viewport_width=800, viewport_height=40)
    assert nothing == []

    # After enough time for the gap (> 500 px at speed=400 px/s → 1.25s)
    enough = manager.tick(now=1.5, viewport_width=800, viewport_height=40)
    assert len(enough) == 1
    assert manager.active_count == 2  # both still scrolling (duration=2s each)


def test_tracks_release_after_duration() -> None:
    manager = BasicBarrageManager(density="medium")
    manager.enqueue([make_item(i, duration_seconds=1.0) for i in range(3)])

    first = manager.tick(now=0.0, viewport_width=800, viewport_height=60)
    assert len(first) == 1  # only 1 track at 60px height
    assert manager.active_count == 1

    # After duration: item released, track free again
    second = manager.tick(now=1.1, viewport_width=800, viewport_height=60)
    assert len(second) == 1
    assert manager.active_count == 1  # old gone, new assigned


def test_enqueue_deduplicates_pending_and_recent_text() -> None:
    manager = BasicBarrageManager(density="high")
    manager.enqueue([
        make_item(1, text="chong fu"),
        make_item(2, text="chong fu"),
        make_item(3, text="  chong fu  "),
    ])

    first_batch = manager.tick(now=0.0, viewport_width=800, viewport_height=600)
    manager.enqueue([make_item(4, text="chong fu")])
    second_batch = manager.tick(now=1.0, viewport_width=800, viewport_height=600)

    assert len(first_batch) == 1
    assert second_batch == []
    assert manager.pending_count == 0


def test_duplicate_text_can_return_after_duplicate_window_expires() -> None:
    manager = BasicBarrageManager(density="high", duplicate_window_seconds=1.0)
    manager.enqueue([make_item(1, text="return", duration_seconds=0.5)])
    manager.tick(now=0.0, viewport_width=800, viewport_height=600)

    manager.tick(now=1.1, viewport_width=800, viewport_height=600)
    manager.enqueue([make_item(2, text="return", duration_seconds=0.5)])
    second_batch = manager.tick(now=1.2, viewport_width=800, viewport_height=600)

    assert len(second_batch) == 1


def test_pause_blocks_new_assignments_until_resume() -> None:
    manager = BasicBarrageManager(density="medium")
    manager.enqueue([make_item(i) for i in range(3)])

    manager.pause()
    paused_batch = manager.tick(now=0.0, viewport_width=800, viewport_height=600)
    manager.resume()
    resumed_batch = manager.tick(now=0.1, viewport_width=800, viewport_height=600)

    assert paused_batch == []
    assert len(resumed_batch) == 3


def test_priority_items_are_scheduled_first() -> None:
    manager = BasicBarrageManager(density="medium")
    manager.enqueue([
        make_item(1, text="normal", priority=0, created_at=1.0),
        make_item(2, text="high energy", priority=10, created_at=2.0),
    ])

    assignments = manager.tick(now=0.0, viewport_width=800, viewport_height=600)

    assert [a.item.text for a in assignments] == ["high energy", "normal"]


def test_viewport_height_limits_track_count() -> None:
    manager = BasicBarrageManager(density="high")
    manager.enqueue([make_item(i) for i in range(5)])

    assignments = manager.tick(now=0.0, viewport_width=800, viewport_height=70)

    assert len(assignments) == 1
    assert assignments[0].track_index == 0


def test_invalid_density_raises_error() -> None:
    manager = BasicBarrageManager()

    with pytest.raises(ValueError):
        manager.set_density("extreme")


def test_low_density_has_larger_gap_than_high() -> None:
    assert DENSITY_GAP["low"] > DENSITY_GAP["medium"] > DENSITY_GAP["high"]
