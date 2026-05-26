from app.core.barrage_cache import InMemoryBarrageCache
from app.models import BarrageItem, SceneSummary


def make_item(index: int, text: str) -> BarrageItem:
    return BarrageItem(
        id=f"id-{index}",
        text=text,
        persona="fun",
        priority=0,
        created_at=0.0,
        duration_seconds=1.0,
    )


def test_cache_returns_items_for_same_scene() -> None:
    cache = InMemoryBarrageCache()
    scene = SceneSummary(
        activity="active",
        pace="normal",
        event="normal",
        confidence=0.6,
    )

    cache.put(scene, [make_item(1, "一条"), make_item(2, "二条")])
    items = cache.get(scene, 1)

    assert len(items) == 1
    assert items[0].text == "一条"


def test_cache_deduplicates_text() -> None:
    cache = InMemoryBarrageCache()
    scene = SceneSummary(
        activity="active",
        pace="normal",
        event="normal",
        confidence=0.6,
    )

    cache.put(scene, [make_item(1, "重复")])
    cache.put(scene, [make_item(2, "重复"), make_item(3, "新")])

    assert [item.text for item in cache.get(scene, 5)] == ["重复", "新"]


def test_cache_caps_items_per_scene() -> None:
    cache = InMemoryBarrageCache(max_items_per_scene=10)
    scene = SceneSummary(
        activity="active",
        pace="normal",
        event="normal",
        confidence=0.6,
    )

    cache.put(scene, [make_item(index, f"弹幕{index}") for index in range(12)])

    assert len(cache.get(scene, 20)) == 10
    assert cache.get(scene, 20)[0].text == "弹幕2"
