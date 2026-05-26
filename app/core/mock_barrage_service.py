"""Local barrage generation used when no AI API is configured."""

from __future__ import annotations

import random
import time
from uuid import uuid4

from app.constants import DEFAULT_BARRAGE_DURATION_SECONDS
from app.models import BarrageItem, GenerationRequest, GenerationResult, Persona, SceneEvent


DEFAULT_PERSONAS: list[Persona] = [
    "troll",
    "support",
    "sarcastic",
    "follower",
    "fun",
]

TEMPLATES: dict[SceneEvent, dict[Persona, list[str]]] = {
    "normal": {
        "troll": ["这也行啊", "有点东西", "别急"],
        "support": ["稳住稳住", "可以的", "慢慢来"],
        "sarcastic": ["很有想法", "懂了懂了", "就这节奏"],
        "follower": ["前面说得对", "确实", "跟了"],
        "fun": ["节目来了", "有画面了", "开演"],
    },
    "highlight": {
        "troll": ["差点翻车", "手忙脚乱", "别装"],
        "support": ["这波漂亮", "太稳了", "继续冲"],
        "sarcastic": ["主播醒了", "突然会了", "有操作"],
        "follower": ["这波可以", "前面别奶", "来了来了"],
        "fun": ["高能来了", "弹幕刷起来", "有节目"],
    },
    "stuck": {
        "troll": ["卡住了吧", "又来了", "不会吧"],
        "support": ["别慌", "再试一次", "能过"],
        "sarcastic": ["熟悉环节", "开始研究", "很沉浸"],
        "follower": ["我也卡这", "确实难", "前面等下"],
        "fun": ["经典复刻", "节目效果", "开始坐牢"],
    },
    "idle": {
        "troll": ["人呢", "挂机了", "睡着了"],
        "support": ["休息一下", "喝口水", "慢慢来"],
        "sarcastic": ["战略暂停", "空气直播", "很安静"],
        "follower": ["人呢人呢", "还在吗", "等一下"],
        "fun": ["直播事故", "静音现场", "弹幕接管"],
    },
}


class MockBarrageService:
    """Generate short local barrage items without network access."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()

    def generate(self, request: GenerationRequest) -> GenerationResult:
        personas = request.personas or DEFAULT_PERSONAS
        count = max(0, min(request.count, 5))
        event_templates = TEMPLATES.get(request.scene.event, TEMPLATES["normal"])
        created_at = time.time()
        items: list[BarrageItem] = []
        used_texts: set[str] = set()

        for index in range(count):
            persona = personas[index % len(personas)]
            text = self._pick_text(event_templates, persona, used_texts)
            if text is None:
                break

            used_texts.add(text)
            items.append(
                BarrageItem(
                    id=str(uuid4()),
                    text=text,
                    persona=persona,
                    priority=self._priority_for_event(request.scene.event),
                    created_at=created_at,
                    duration_seconds=DEFAULT_BARRAGE_DURATION_SECONDS,
                )
            )

        return GenerationResult(items=items, source="mock")

    def _pick_text(
        self,
        event_templates: dict[Persona, list[str]],
        persona: Persona,
        used_texts: set[str],
    ) -> str | None:
        candidates = event_templates.get(persona) or TEMPLATES["normal"][persona]
        available = [text for text in candidates if text not in used_texts]
        if not available:
            return None
        return self._rng.choice(available)

    @staticmethod
    def _priority_for_event(event: SceneEvent) -> int:
        if event == "highlight":
            return 10
        if event == "stuck":
            return 5
        return 0
