"""In-memory barrage cache keyed by coarse scene state."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace

from app.models import BarrageItem, SceneSummary


class InMemoryBarrageCache:
    """Small FIFO cache for reusable scene comments."""

    def __init__(self, max_scenes: int = 32, max_items_per_scene: int = 10) -> None:
        self._max_scenes = max(1, max_scenes)
        self._max_items_per_scene = max(1, max_items_per_scene)
        self._items: OrderedDict[tuple[str, str, str], list[BarrageItem]] = OrderedDict()

    def get(self, scene: SceneSummary, count: int) -> list[BarrageItem]:
        key = self._key(scene)
        items = self._items.get(key, [])
        if not items:
            return []
        self._items.move_to_end(key)
        return [replace(item) for item in items[: max(0, count)]]

    def put(self, scene: SceneSummary, items: list[BarrageItem]) -> None:
        if not items:
            return
        key = self._key(scene)
        existing = self._items.get(key, [])
        seen = {item.text for item in existing}
        merged = existing[:]
        for item in items:
            if item.text not in seen:
                merged.append(replace(item))
                seen.add(item.text)

        self._items[key] = merged[-self._max_items_per_scene :]
        self._items.move_to_end(key)
        while len(self._items) > self._max_scenes:
            self._items.popitem(last=False)

    @staticmethod
    def _key(scene: SceneSummary) -> tuple[str, str, str]:
        return (scene.activity, scene.pace, scene.event)
