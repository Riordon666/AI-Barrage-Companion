"""Local mock barrage generation for demos and AI fallback."""

from __future__ import annotations

import hashlib
import time
from itertools import cycle
from typing import Callable

from app.constants import DEFAULT_BARRAGE_DURATION_SECONDS
from app.models import (
    BarrageItem,
    GenerationRequest,
    GenerationResult,
    Persona,
    SceneSummary,
)


DEFAULT_PERSONAS: list[Persona] = [
    "troll",
    "support",
    "sarcastic",
    "follower",
    "fun",
]


MOCK_LINES: dict[str, list[tuple[Persona, str, int]]] = {
    "idle": [
        ("troll", "主播挂机了", 0),
        ("fun", "人呢人呢", 0),
        ("sarcastic", "这段留白妙", 0),
        ("support", "休息也行", 0),
    ],
    "stuck": [
        ("troll", "卡住了吧", 2),
        ("support", "稳住快好了", 2),
        ("sarcastic", "熟悉的报错", 2),
        ("fun", "节目效果来了", 2),
    ],
    "highlight": [
        ("support", "这波可以", 10),
        ("fun", "燃起来了", 10),
        ("follower", "前面的对", 8),
        ("troll", "别急别急", 8),
    ],
    "normal": [
        ("support", "节奏不错", 0),
        ("troll", "这也能行", 0),
        ("follower", "确实确实", 0),
        ("fun", "有点意思", 0),
    ],
    "fast": [
        ("fun", "眼睛跟不上", 6),
        ("support", "操作起来了", 6),
        ("troll", "别手抖", 6),
        ("follower", "太快了吧", 6),
    ],
}


class MockBarrageService:
    """Generate short local barrage items without network access."""

    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self._now = now or time.time

    def generate(self, request: GenerationRequest) -> GenerationResult:
        count = max(0, request.count)
        if count == 0:
            return GenerationResult(items=[], source="mock")

        allowed_personas = request.personas or DEFAULT_PERSONAS
        candidates = self._candidates_for(request.scene)
        filtered = [
            candidate
            for candidate in candidates
            if candidate[0] in allowed_personas
        ]
        if not filtered:
            filtered = candidates

        now = self._now()
        items: list[BarrageItem] = []
        seen_text: set[str] = set()

        for persona, text, priority in cycle(filtered):
            if text not in seen_text:
                items.append(
                    BarrageItem(
                        id=self._item_id(request.scene, text, len(items), now),
                        text=text,
                        persona=persona,
                        priority=priority,
                        created_at=now,
                        duration_seconds=DEFAULT_BARRAGE_DURATION_SECONDS,
                    )
                )
                seen_text.add(text)
            if len(items) >= count or len(seen_text) >= len(filtered):
                break

        return GenerationResult(items=items, source="mock")

    def _candidates_for(
        self,
        scene: SceneSummary,
    ) -> list[tuple[Persona, str, int]]:
        candidates: list[tuple[Persona, str, int]] = []

        if scene.event in MOCK_LINES:
            candidates.extend(MOCK_LINES[scene.event])
        if scene.pace == "fast":
            candidates.extend(MOCK_LINES["fast"])
        candidates.extend(MOCK_LINES["normal"])

        unique_candidates: list[tuple[Persona, str, int]] = []
        seen_text: set[str] = set()
        for candidate in candidates:
            text = candidate[1]
            if text in seen_text:
                continue
            unique_candidates.append(candidate)
            seen_text.add(text)
        return unique_candidates

    def _item_id(
        self,
        scene: SceneSummary,
        text: str,
        index: int,
        now: float,
    ) -> str:
        raw = f"{scene.activity}:{scene.pace}:{scene.event}:{text}:{index}:{now}"
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"mock-{digest}"
