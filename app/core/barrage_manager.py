"""Barrage queueing, de-duplication, density limiting, and track assignment."""

from __future__ import annotations

from dataclasses import dataclass

from app.constants import (
    DEFAULT_DUPLICATE_WINDOW_SECONDS,
    DEFAULT_MIN_BARRAGE_SPEED,
    DEFAULT_TRACK_GAP,
    DEFAULT_TRACK_HEIGHT,
)
from app.models import BarrageItem, Density, TrackAssignment


DENSITY_LIMITS: dict[Density, int] = {
    "low": 3,
    "medium": 6,
    "high": 10,
}


@dataclass
class _ActiveTrack:
    assignment: TrackAssignment
    release_at: float


class BasicBarrageManager:
    """Schedule barrage items onto tracks without touching UI code."""

    def __init__(
        self,
        density: Density = "medium",
        track_height: int = DEFAULT_TRACK_HEIGHT,
        track_gap: int = DEFAULT_TRACK_GAP,
        duplicate_window_seconds: float = DEFAULT_DUPLICATE_WINDOW_SECONDS,
    ) -> None:
        self._density: Density = density
        self._track_height = track_height
        self._track_gap = track_gap
        self._duplicate_window_seconds = duplicate_window_seconds
        self._pending: list[BarrageItem] = []
        self._active: dict[int, _ActiveTrack] = {}
        self._recent_texts: dict[str, float] = {}
        self._paused = False

    def enqueue(self, items: list[BarrageItem]) -> None:
        for item in items:
            normalized_text = self._normalize_text(item.text)
            if not normalized_text:
                continue
            if normalized_text in self._recent_texts:
                continue
            if any(self._normalize_text(pending.text) == normalized_text for pending in self._pending):
                continue
            if any(
                self._normalize_text(active.assignment.item.text) == normalized_text
                for active in self._active.values()
            ):
                continue
            self._pending.append(item)

        self._pending.sort(key=lambda item: (-item.priority, item.created_at))

    def tick(
        self,
        now: float,
        viewport_width: int,
        viewport_height: int,
    ) -> list[TrackAssignment]:
        self._release_finished_tracks(now)
        self._expire_recent_texts(now)

        if self._paused:
            return []

        max_visible = self._max_visible(viewport_height)
        available_slots = max(0, max_visible - len(self._active))
        if available_slots == 0:
            return []

        assignments: list[TrackAssignment] = []
        free_tracks = self._free_tracks(max_visible)

        while self._pending and free_tracks and available_slots > 0:
            item = self._pending.pop(0)
            track_index = free_tracks.pop(0)
            assignment = self._assign(item, track_index, viewport_width)
            self._active[track_index] = _ActiveTrack(
                assignment=assignment,
                release_at=now + max(0.1, item.duration_seconds),
            )
            self._recent_texts[self._normalize_text(item.text)] = now + self._duplicate_window_seconds
            assignments.append(assignment)
            available_slots -= 1

        return assignments

    def set_density(self, density: str) -> None:
        if density not in DENSITY_LIMITS:
            raise ValueError(f"Unsupported density: {density}")
        self._density = density  # type: ignore[assignment]

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def _assign(self, item: BarrageItem, track_index: int, viewport_width: int) -> TrackAssignment:
        duration = max(0.1, item.duration_seconds)
        return TrackAssignment(
            item=item,
            track_index=track_index,
            start_x=viewport_width,
            y=track_index * (self._track_height + self._track_gap),
            speed_px_per_second=max(DEFAULT_MIN_BARRAGE_SPEED, viewport_width / duration),
        )

    def _release_finished_tracks(self, now: float) -> None:
        expired = [
            track_index
            for track_index, active in self._active.items()
            if active.release_at <= now
        ]
        for track_index in expired:
            del self._active[track_index]

    def _expire_recent_texts(self, now: float) -> None:
        expired = [
            text
            for text, expires_at in self._recent_texts.items()
            if expires_at <= now
        ]
        for text in expired:
            del self._recent_texts[text]

    def _free_tracks(self, max_visible: int) -> list[int]:
        return [
            track_index
            for track_index in range(max_visible)
            if track_index not in self._active
        ]

    def _max_visible(self, viewport_height: int) -> int:
        track_stride = max(1, self._track_height + self._track_gap)
        track_capacity = max(1, viewport_height // track_stride)
        return min(DENSITY_LIMITS[self._density], track_capacity)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.strip().split())
