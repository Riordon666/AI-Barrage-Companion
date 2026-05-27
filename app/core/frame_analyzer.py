"""Lightweight local frame-difference analysis."""

from __future__ import annotations

from typing import cast

from app.core.utils import as_activity, as_scene_event, raw_image_bytes
from app.models import Activity, CapturedFrame, FrameStats, Pace, SceneSummary, SceneEvent


class BasicFrameAnalyzer:
    """Turn frame pixels into coarse scene signals without OCR."""

    def __init__(self, sample_width: int = 32, sample_height: int = 18) -> None:
        self._sample_width = sample_width
        self._sample_height = sample_height
        self._previous_samples: list[int] | None = None
        self._previous_timestamp: float | None = None
        self._static_seconds = 0.0

    def analyze(self, frame: CapturedFrame) -> tuple[FrameStats, SceneSummary]:
        samples = self._sample(frame)
        if self._previous_samples is None:
            change_ratio = 1.0
            self._static_seconds = 0.0
        else:
            change_ratio = self._change_ratio(self._previous_samples, samples)
            previous_timestamp = (
                self._previous_timestamp
                if self._previous_timestamp is not None
                else frame.timestamp
            )
            elapsed = max(0.0, frame.timestamp - previous_timestamp)
            if change_ratio < 0.02:
                self._static_seconds += elapsed
            else:
                self._static_seconds = 0.0

        repeat_score = max(0.0, min(1.0, 1.0 - change_ratio))
        pace = self._pace_for(change_ratio)
        event = "normal"
        activity = "active"

        if change_ratio < 0.02 and self._static_seconds >= 10.0:
            event = "idle"
            activity = "idle"
            pace = "idle"
        elif repeat_score > 0.92 and change_ratio < 0.08 and self._static_seconds >= 3.0:
            event = "stuck"
            activity = "repeated"
        elif change_ratio > 0.25:
            event = "highlight"
            activity = "active"
        elif change_ratio < 0.02:
            activity = "idle"

        confidence = self._confidence_for(change_ratio)
        stats = FrameStats(
            change_ratio=change_ratio,
            static_seconds=self._static_seconds,
            repeat_score=repeat_score,
            pace=cast(Pace, pace),
        )
        scene = SceneSummary(
            activity=as_activity(activity),
            pace=cast(Pace, pace),
            event=as_scene_event(event),
            confidence=confidence,
        )

        self._previous_samples = samples
        self._previous_timestamp = frame.timestamp
        return stats, scene

    def _sample(self, frame: CapturedFrame) -> list[int]:
        raw = raw_image_bytes(frame.image)
        if not raw:
            return [0] * (self._sample_width * self._sample_height)

        bytes_per_pixel = max(1, len(raw) // max(1, frame.width * frame.height))
        samples: list[int] = []
        for sy in range(self._sample_height):
            y = min(frame.height - 1, sy * frame.height // self._sample_height)
            for sx in range(self._sample_width):
                x = min(frame.width - 1, sx * frame.width // self._sample_width)
                offset = (y * frame.width + x) * bytes_per_pixel
                pixel = raw[offset : offset + bytes_per_pixel]
                if len(pixel) >= 3:
                    samples.append((int(pixel[0]) + int(pixel[1]) + int(pixel[2])) // 3)
                elif pixel:
                    samples.append(int(pixel[0]))
                else:
                    samples.append(0)
        return samples

    @staticmethod
    def _change_ratio(previous: list[int], current: list[int]) -> float:
        if not previous or len(previous) != len(current):
            return 1.0
        total = sum(abs(a - b) for a, b in zip(previous, current))
        return min(1.0, total / (len(current) * 255.0))

    @staticmethod
    def _pace_for(change_ratio: float) -> str:
        if change_ratio < 0.02:
            return "idle"
        if change_ratio < 0.08:
            return "slow"
        if change_ratio > 0.25:
            return "fast"
        return "normal"

    @staticmethod
    def _confidence_for(change_ratio: float) -> float:
        if change_ratio < 0.02 or change_ratio > 0.25:
            return 0.85
        return 0.65
