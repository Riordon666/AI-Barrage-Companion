"""OpenAI-compatible barrage generation service."""

from __future__ import annotations

import base64
import io
import json
import re
import time
from typing import Any
from uuid import uuid4

import httpx
from PIL import Image

import logging

from app.constants import DEFAULT_BARRAGE_DURATION_SECONDS
from app.config.provider_presets import provider_for_key
from app.core.mock_barrage_service import DEFAULT_PERSONAS, MockBarrageService
from app.core.utils import as_persona, priority_for_event, raw_image_bytes
from app.models import ApiConfig, BarrageItem, CapturedFrame, GenerationRequest, GenerationResult, Persona, SceneEvent

logger = logging.getLogger("abc.ai_service")


VALID_PERSONAS = set(DEFAULT_PERSONAS)


def encode_frame_jpeg_base64(frame: CapturedFrame, quality: int = 50) -> str:
    """Convert a mss CapturedFrame to a base64 data-uri JPEG string."""
    raw = raw_image_bytes(frame.image)
    bpp = max(1, len(raw) // max(1, frame.width * frame.height))
    if bpp >= 3:
        raw_mode = _mss_raw_mode()
        pil_image = Image.frombuffer("RGB", (frame.width, frame.height), raw, "raw", raw_mode)
    else:
        # Grayscale fallback
        pil_image = Image.frombuffer("L", (frame.width, frame.height), raw, "raw", "L")

    # Resize to reduce token cost (max 512 on the longest side)
    scale = min(512 / frame.width, 512 / frame.height)
    if scale < 1.0:
        new_size = (int(frame.width * scale), int(frame.height * scale))
        pil_image = pil_image.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _mss_raw_mode() -> str:
    """Return the correct mss raw pixel mode for the current platform."""
    import sys

    if sys.platform == "win32":
        return "BGRX"
    return "BGRA"


class OpenAICompatibleBarrageService:
    """Generate barrage items through an OpenAI-style chat completions API."""

    # Per-session cache: (base_url, model) → vision support known to be broken
    _vision_disabled: set[tuple[str, str]] = set()

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

        # Skip vision if this model is known to reject images
        vision_key = (self._api_config.base_url, self._api_config.model)
        if request.image_base64 and vision_key in self._vision_disabled:
            request.image_base64 = None

        try:
            content = self._request_content(request)
        except httpx.HTTPStatusError as http_exc:
            if request.image_base64 and http_exc.response.status_code in (400, 404, 422):
                self._vision_disabled.add(vision_key)
                logger.info("视觉请求不被模型支持（已记住），回退纯文本重试")
                request.image_base64 = None
                try:
                    content = self._request_content(request)
                except Exception as exc:
                    logger.warning("纯文本重试也失败: %s", exc)
                    fallback = self._fallback.generate(request)
                    fallback.error = "api_error_retry"
                    return fallback
            else:
                logger.warning("API HTTP 错误: %s", http_exc)
                fallback = self._fallback.generate(request)
                fallback.error = "api_error"
                return fallback
        except (httpx.RequestError, json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("API 请求异常: %s", exc)
            fallback = self._fallback.generate(request)
            fallback.error = "api_error"
            return fallback

        items = self.parse_items(content, request)
        if not items:
            fallback = self._fallback.generate(request)
            fallback.error = "empty_ai_result"
            return fallback
        return GenerationResult(items=items, source="ai")

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
                    persona=as_persona(persona),
                    priority=priority_for_event(request.scene.event),
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

        user_content: str | list[dict[str, Any]]
        if request.image_base64:
            # Vision API format: image + text
            user_content = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{request.image_base64}",
                        "detail": "low",
                    },
                },
                {"type": "text", "text": self._user_prompt(request)},
            ]
        else:
            user_content = self._user_prompt(request)

        payload: dict[str, Any] = {
            "model": self._api_config.model,
            "messages": [
                {"role": "system", "content": self._system_prompt(request)},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.8,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_config.api_key:
            headers["Authorization"] = f"Bearer {self._api_config.api_key}"

        # Extract text part of user_content for logging (may be str or vision list)
        user_text = user_content if isinstance(user_content, str) else (
            next((b["text"] for b in user_content if isinstance(b, dict) and b.get("type") == "text"), "")
        )
        try:
            logger.info(
                "[HTTP 请求] %s | model=%s | prompt_len=%d | image=%s",
                url, self._api_config.model, len(user_text),
                "YES" if request.image_base64 else "NO",
            )
        except Exception:
            pass  # graceful with mock/test clients

        def _do_post(client: httpx.Client) -> str:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content = str(data["choices"][0]["message"]["content"])
            try:
                logger.info(
                    "[HTTP 响应] status=%d | content_len=%d | preview=%.120s",
                    response.status_code, len(content), content,
                )
            except Exception:
                pass  # mock client may not expose status_code
            return content

        if self._client is not None:
            return _do_post(self._client)

        with httpx.Client(timeout=self._api_config.timeout_seconds) as client:
            return _do_post(client)

    @staticmethod
    def _system_prompt(request: GenerationRequest) -> str:
        base = (
            "你是直播间观众，只输出 JSON 数组。"
            "每条弹幕 1 到 12 个中文字符，不要脏话、人身攻击或隐私内容。"
        )
        if request.image_base64:
            base += (
                "你可以看到用户当前的屏幕截图，请仔细观察画面内容（代码、游戏、编辑器、网页等），"
                "生成贴合实际场景的弹幕。"
            )
        return base

    @staticmethod
    def _user_prompt(request: GenerationRequest) -> str:
        scene = request.scene
        lines = [
            f"场景信号: activity={scene.activity}, pace={scene.pace}, "
            f"event={scene.event}, confidence={scene.confidence:.2f}",
        ]

        # --- Screen context: the key addition ---
        if scene.screen_context:
            lines.append(f"屏幕内容: {scene.screen_context}")
            lines.append("请根据上述屏幕内容生成弹幕，弹幕要和用户正在做的事相关。")
        # ----------------------------------------

        lines += [
            f"人格可选: {', '.join(request.personas or DEFAULT_PERSONAS)}",
            f"数量: {request.count}",
            '格式: [{"persona":"fun","text":"有点意思"}]',
        ]
        return "\n".join(lines)

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
        # Normalise Unicode to avoid splitting composite characters, then
        # strip whitespace and hard-cap at 12 characters.
        import unicodedata

        text = unicodedata.normalize("NFC", text)
        text = re.sub(r"\s+", "", text)
        return text[:12]
