"""Barrage queueing, de-duplication, density (spacing), and track assignment."""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.constants import (
    DEFAULT_DUPLICATE_WINDOW_SECONDS,
    DEFAULT_MIN_BARRAGE_SPEED,
    DEFAULT_TRACK_GAP,
    DEFAULT_TRACK_HEIGHT,
    HIGHLIGHT_GAP_DIVISOR,
)
from app.models import BarrageItem, Density, TrackAssignment

# Minimum horizontal gap (pixels) between consecutive barrages on the same track.
# Density controls spacing rather than a hard cap on visible count.
DENSITY_GAP: dict[Density, int] = {
    "low": 500,
    "medium": 250,
    "high": 100,
}


@dataclass
class _ActiveEntry:
    assignment: TrackAssignment
    release_at: float


class BasicBarrageManager:
    """Schedule barrage items onto tracks.  Multiple barrages may share a track
    as long as the previous one has scrolled past the density gap."""

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
        # Each track holds zero or more currently scrolling barrages.
        self._active: dict[int, list[_ActiveEntry]] = {}
        self._recent_texts: dict[str, float] = {}
        self._paused = False
        self._burst_mode = False

    # -- public API ---------------------------------------------------------

    def enqueue(self, items: list[BarrageItem]) -> None:
        for item in items:
            normalized_text = self._normalize_text(item.text)
            if not normalized_text:
                continue
            if normalized_text in self._recent_texts:
                continue
            if any(self._normalize_text(p.text) == normalized_text for p in self._pending):
                continue
            if any(
                self._normalize_text(entry.assignment.item.text) == normalized_text
                for entries in self._active.values()
                for entry in entries
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
        self._release_finished(now)
        self._expire_recent_texts(now)

        if self._paused:
            return []

        track_count = max(1, viewport_height // max(1, self._track_height + self._track_gap))
        gap_px = DENSITY_GAP[self._density]

        assignments: list[TrackAssignment] = []
        eligible = self._eligible_tracks(now, viewport_width, track_count, gap_px)
        random.shuffle(eligible)

        while self._pending and eligible:
            item = self._pending.pop(0)
            # Pick the track with the fewest active barrages to spread evenly
            eligible.sort(key=lambda t: len(self._active.get(t, [])))
            track_index = eligible.pop(0)
            if not eligible:
                pass  # last track, fine to reuse
            elif track_index in self._active and eligible:
                current_load = len(self._active.get(track_index, []))
                min_load = min(len(self._active.get(t, [])) for t in eligible)
                if current_load - min_load >= 2:
                    eligible.sort(key=lambda t: len(self._active.get(t, [])))
                    track_index = eligible.pop(0)

            # Prevent overtaking: clamp new barrage speed to ≤ previous on same track
            prev_speed = None
            entries = self._active.get(track_index)
            if entries:
                prev_speed = entries[-1].assignment.speed_px_per_second
            assignment = self._assign(item, track_index, viewport_width, prev_speed)
            self._active.setdefault(track_index, []).append(
                _ActiveEntry(
                    assignment=assignment,
                    release_at=now + max(0.1, item.duration_seconds),
                )
            )
            self._recent_texts[self._normalize_text(item.text)] = (
                now + self._duplicate_window_seconds
            )
            assignments.append(assignment)

        return assignments

    def set_density(self, density: str) -> None:
        if density not in DENSITY_GAP:
            raise ValueError(f"Unsupported density: {density}")
        self._density = density  # type: ignore[assignment]

    def set_track_layout(self, track_height: int, track_gap: int | None = None) -> None:
        self._track_height = max(1, track_height)
        if track_gap is not None:
            self._track_gap = max(0, track_gap)

    def set_burst(self, enabled: bool) -> None:
        self._burst_mode = enabled

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def active_count(self) -> int:
        return sum(len(entries) for entries in self._active.values())

    # -- internals ----------------------------------------------------------

    def _assign(
        self,
        item: BarrageItem,
        track_index: int,
        viewport_width: int,
        max_speed: float | None = None,
    ) -> TrackAssignment:
        duration = max(0.1, item.duration_seconds)
        speed = max(DEFAULT_MIN_BARRAGE_SPEED, viewport_width / duration)
        # Clamp to preceding barrage speed so we never overtake on the same track.
        if max_speed is not None and speed > max_speed:
            speed = max_speed
        return TrackAssignment(
            item=item,
            track_index=track_index,
            start_x=viewport_width,
            y=track_index * (self._track_height + self._track_gap),
            speed_px_per_second=speed,
        )

    def _release_finished(self, now: float) -> None:
        for entries in list(self._active.values()):
            entries[:] = [e for e in entries if e.release_at > now]
        # Drop empty tracks
        self._active = {
            track_idx: entries
            for track_idx, entries in self._active.items()
            if entries
        }

    def _eligible_tracks(
        self, now: float, viewport_width: int, track_count: int, min_gap_px: int,
    ) -> list[int]:
        gap = max(10, min_gap_px // HIGHLIGHT_GAP_DIVISOR) if self._burst_mode else min_gap_px
        result: list[int] = []
        for track_index in range(track_count):
            entries = self._active.get(track_index)
            if not entries:
                result.append(track_index)
                continue
            last = entries[-1]
            elapsed = max(0.0, now - last.assignment.item.created_at)
            if elapsed * last.assignment.speed_px_per_second >= gap:
                result.append(track_index)
        return result

    def _expire_recent_texts(self, now: float) -> None:
        self._recent_texts = {
            text: exp for text, exp in self._recent_texts.items() if exp > now
        }

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.strip().split())
