import random

from app.core.mock_barrage_service import MockBarrageService
from app.models import GenerationRequest, SceneSummary


def test_mock_barrage_generates_requested_count() -> None:
    service = MockBarrageService(rng=random.Random(1))
    request = GenerationRequest(
        scene=SceneSummary(
            activity="active",
            pace="fast",
            event="highlight",
            confidence=0.9,
        ),
        density="medium",
        personas=["troll", "support", "fun"],
        count=3,
    )

    result = service.generate(request)

    assert result.source == "mock"
    assert result.error is None
    assert len(result.items) == 3
    assert {item.persona for item in result.items} == {"troll", "support", "fun"}
    assert all(item.priority == 10 for item in result.items)
    assert all(1 <= len(item.text) <= 12 for item in result.items)


def test_mock_barrage_clamps_count_to_five() -> None:
    service = MockBarrageService(rng=random.Random(2))
    request = GenerationRequest(
        scene=SceneSummary(
            activity="idle",
            pace="idle",
            event="idle",
            confidence=0.3,
        ),
        density="high",
        personas=[],
        count=10,
    )

    result = service.generate(request)

    ids = [item.id for item in result.items]

    assert result.source == "mock"
    assert len(result.items) == 5
    assert len(ids) == len(set(ids))


def test_mock_barrage_uses_stuck_priority() -> None:
    service = MockBarrageService(rng=random.Random(3))
    request = GenerationRequest(
        scene=SceneSummary(
            activity="repeated",
            pace="slow",
            event="stuck",
            confidence=0.7,
        ),
        density="low",
        personas=["support"],
        count=1,
    )

    result = service.generate(request)

    assert result.items[0].priority == 5
