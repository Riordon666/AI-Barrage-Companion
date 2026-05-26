from app.core.ai_service import OpenAICompatibleBarrageService
from app.core.mock_barrage_service import MockBarrageService
from app.models import ApiConfig, GenerationRequest, SceneSummary


def make_request() -> GenerationRequest:
    return GenerationRequest(
        scene=SceneSummary(
            activity="active",
            pace="fast",
            event="highlight",
            confidence=0.8,
        ),
        density="medium",
        personas=["support", "fun"],
        count=2,
    )


def test_ai_service_parses_json_array() -> None:
    service = OpenAICompatibleBarrageService(api_config=None)

    items = service.parse_items(
        '[{"persona":"support","text":"稳住能赢"},{"persona":"fun","text":"节目来了"}]',
        make_request(),
    )

    assert len(items) == 2
    assert items[0].persona == "support"
    assert items[0].priority == 10


def test_ai_service_falls_back_without_api_config() -> None:
    service = OpenAICompatibleBarrageService(
        api_config=None,
        fallback=MockBarrageService(),
    )

    result = service.generate(make_request())

    assert result.source == "mock"
    assert result.error == "missing_api_config"
    assert result.items


def test_ai_service_falls_back_when_required_api_key_is_missing() -> None:
    service = OpenAICompatibleBarrageService(
        api_config=ApiConfig(
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="",
            model="deepseek-chat",
        ),
        fallback=MockBarrageService(),
    )

    result = service.generate(make_request())

    assert result.source == "mock"
    assert result.error == "missing_api_key"
    assert result.items


def test_ai_service_allows_ollama_without_api_key() -> None:
    class FakeClient:
        def post(self, url, headers, json):  # type: ignore[no-untyped-def]
            assert "Authorization" not in headers
            return self

        def raise_for_status(self) -> None:
            return None

        def json(self):  # type: ignore[no-untyped-def]
            return {
                "choices": [
                    {
                        "message": {
                            "content": '[{"persona":"fun","text":"本地也行"}]',
                        }
                    }
                ]
            }

    service = OpenAICompatibleBarrageService(
        api_config=ApiConfig(
            provider="ollama",
            base_url="http://localhost:11434/v1",
            api_key="",
            model="qwen2.5:7b",
        ),
        fallback=MockBarrageService(),
        client=FakeClient(),
    )

    result = service.generate(make_request())

    assert result.source == "ai"
    assert result.items[0].text == "本地也行"
