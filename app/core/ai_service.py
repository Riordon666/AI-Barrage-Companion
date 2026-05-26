"""OpenAI-compatible barrage generation service."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from uuid import uuid4

import httpx

from app.constants import DEFAULT_BARRAGE_DURATION_SECONDS
from app.config.provider_presets import provider_for_key
from app.core.mock_barrage_service import DEFAULT_PERSONAS, MockBarrageService
from app.models import ApiConfig, BarrageItem, GenerationRequest, GenerationResult, Persona, SceneEvent


VALID_PERSONAS = set(DEFAULT_PERSONAS)


class OpenAICompatibleBarrageService:
    """Generate barrage items through an OpenAI-style chat completions API."""

    def __init__(
        self,
        api_config: ApiConfig | None,
        fallback: MockBarrageService | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_config = api_config
        self._fallback = fallback or MockBarrageService()
        self._client = client

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if self._api_config is None:
            fallback = self._fallback.generate(request)
            fallback.error = "missing_api_config"
            return fallback

        preset = provider_for_key(self._api_config.provider)
        if preset.requires_api_key and not self._api_config.api_key:
            fallback = self._fallback.generate(request)
            fallback.error = "missing_api_key"
            return fallback

        try:
            content = self._request_content(request)
            items = self.parse_items(content, request)
            if not items:
                fallback = self._fallback.generate(request)
                fallback.error = "empty_ai_result"
                return fallback
            return GenerationResult(items=items, source="ai")
        except Exception:
            fallback = self._fallback.generate(request)
            fallback.error = "api_error"
            return fallback

    def parse_items(self, content: str, request: GenerationRequest) -> list[BarrageItem]:
        parsed = self._parse_json_array(content)
        raw_items: list[dict[str, Any]] = []
        if isinstance(parsed, list):
            raw_items = [item for item in parsed if isinstance(item, dict)]
        else:
            raw_items = [{"text": line} for line in self._lines_from_text(content)]

        now = time.time()
        items: list[BarrageItem] = []
        seen_texts: set[str] = set()
        allowed_personas = set(request.personas or DEFAULT_PERSONAS)

        for raw in raw_items:
            text = self._clean_text(str(raw.get("text", "")))
            if not text or text in seen_texts:
                continue
            persona = str(raw.get("persona", "fun"))
            if persona not in VALID_PERSONAS or persona not in allowed_personas:
                persona = next(iter(allowed_personas), "fun")
            items.append(
                BarrageItem(
                    id=str(uuid4()),
                    text=text,
                    persona=persona,  # type: ignore[arg-type]
                    priority=self._priority_for_event(request.scene.event),
                    created_at=now,
                    duration_seconds=DEFAULT_BARRAGE_DURATION_SECONDS,
                )
            )
            seen_texts.add(text)
            if len(items) >= request.count:
                break
        return items

    def _request_content(self, request: GenerationRequest) -> str:
        assert self._api_config is not None
        url = self._api_config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self._api_config.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_prompt(request)},
            ],
            "temperature": 0.8,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_config.api_key:
            headers["Authorization"] = f"Bearer {self._api_config.api_key}"
        client = self._client or httpx.Client(timeout=self._api_config.timeout_seconds)
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是直播间观众，只输出 JSON 数组。"
            "每条弹幕 1 到 12 个中文字符，不要脏话、人身攻击或隐私内容。"
        )

    @staticmethod
    def _user_prompt(request: GenerationRequest) -> str:
        scene = request.scene
        return (
            f"场景: activity={scene.activity}, pace={scene.pace}, event={scene.event}, "
            f"confidence={scene.confidence:.2f}\n"
            f"人格可选: {', '.join(request.personas or DEFAULT_PERSONAS)}\n"
            f"数量: {request.count}\n"
            '格式: [{"persona":"fun","text":"有点意思"}]'
        )

    @staticmethod
    def _parse_json_array(content: str) -> Any:
        stripped = content.strip()
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _lines_from_text(content: str) -> list[str]:
        return [line.strip("- 　\t") for line in content.splitlines() if line.strip()]

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"\s+", "", text)
        return text[:12]

    @staticmethod
    def _priority_for_event(event: SceneEvent) -> int:
        if event == "highlight":
            return 10
        if event == "stuck":
            return 5
        return 0
