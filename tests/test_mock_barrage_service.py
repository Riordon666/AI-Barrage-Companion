from app.core.mock_barrage_service import MockBarrageService
from app.models import GenerationRequest, SceneSummary


def test_mock_barrage_service_generates_structured_items() -> None:
    scene = SceneSummary(
        activity="active",
        pace="fast",
        event="highlight",
        confidence=0.9,
    )
    request = GenerationRequest(
        scene=scene,
        density="medium",
        personas=["support", "fun"],
        count=3,
    )

    result = MockBarrageService(now=lambda: 100.0).generate(request)

    assert result.source == "mock"
    assert result.error is None
    assert len(result.items) == 3
    assert {item.persona for item in result.items} <= {"support", "fun"}
    assert all(item.id.startswith("mock-") for item in result.items)
    assert all(item.created_at == 100.0 for item in result.items)


def test_mock_barrage_service_returns_empty_for_zero_count() -> None:
    scene = SceneSummary(
        activity="idle",
        pace="idle",
        event="idle",
        confidence=0.7,
    )
    request = GenerationRequest(
        scene=scene,
        density="low",
        personas=[],
        count=0,
    )

    result = MockBarrageService(now=lambda: 100.0).generate(request)

    assert result.items == []
    assert result.source == "mock"
