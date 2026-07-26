"""OpenAI-compatible barrage generation service.

The OpenAI-protocol path streams the completion and hands each barrage to an
``on_item`` callback the moment its line arrives, instead of waiting for the
whole batch — with 10-30 items per request, that cuts the wait for the first
barrage from the full completion time (5-10s) down to the model's first-token
latency (~1-2s).
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
from dataclasses import replace
from typing import Any, Callable
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


# ── Incremental parsing helpers ─────────────────────────────────────────

def _parse_line_object(line: str) -> dict[str, Any] | None:
    """Parse one output line as a JSON object, tolerating array punctuation."""
    stripped = line.strip().strip("`").lstrip("[").rstrip("]").rstrip(",").strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _looks_like_json_noise(line: str) -> bool:
    """True for structural fragments ('[', '```json', '{') that aren't text."""
    stripped = line.strip().strip("`").strip()
    return (
        not stripped
        or stripped in ("[", "]", "{", "}", ",", "json")
        or stripped.startswith("{")
        or stripped.startswith('"persona"')
    )


def _build_item(
    raw: dict[str, Any],
    request: GenerationRequest,
    allowed_personas: set[str],
    seen_texts: set[str],
    now: float,
) -> BarrageItem | None:
    """Validate one parsed dict into a BarrageItem; None when rejected."""
    text = OpenAICompatibleBarrageService._clean_text(str(raw.get("text", "")))
    if not text or text in seen_texts:
        return None
    persona = str(raw.get("persona", "fun"))
    if persona not in VALID_PERSONAS or persona not in allowed_personas:
        persona = next(iter(allowed_personas), "fun")
    seen_texts.add(text)
    return BarrageItem(
        id=str(uuid4()),
        text=text,
        persona=as_persona(persona),
        priority=priority_for_event(request.scene.event),
        created_at=now,
        duration_seconds=DEFAULT_BARRAGE_DURATION_SECONDS,
    )


class _StreamCollector:
    """Assembles streamed delta text into lines and emits items eagerly.

    One instance serves one request; ``items`` holds everything parsed so far
    in arrival order. The optional ``on_item`` callback fires the moment each
    item parses, which is what lets barrages hit the screen while the model
    is still writing the rest of the batch.
    """

    def __init__(
        self,
        request: GenerationRequest,
        on_item: Callable[[BarrageItem], None] | None,
    ) -> None:
        self._request = request
        self._on_item = on_item
        self._allowed = set(request.personas or DEFAULT_PERSONAS)
        self._seen: set[str] = set()
        self._buffer = ""
        self.full_text = ""
        self.items: list[BarrageItem] = []

    def feed(self, piece: str) -> None:
        self.full_text += piece
        self._buffer += piece
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit_line(line)

    def flush(self) -> None:
        if self._buffer.strip():
            self._emit_line(self._buffer)
        self._buffer = ""

    def add_parsed(self, item: BarrageItem) -> None:
        """Late merge from the full-text safety-net parse."""
        if item.text in self._seen or len(self.items) >= self._request.count:
            return
        self._seen.add(item.text)
        self.items.append(item)
        if self._on_item is not None:
            self._on_item(item)

    def _emit_line(self, line: str) -> None:
        if len(self.items) >= self._request.count:
            return
        obj = _parse_line_object(line)
        if obj is None:
            return
        item = _build_item(obj, self._request, self._allowed, self._seen, time.time())
        if item is None:
            return
        self.items.append(item)
        if self._on_item is not None:
            self._on_item(item)


class OpenAICompatibleBarrageService:
    """Generate barrage items through an OpenAI-style chat completions API."""

    # Per-session caches keyed by (base_url, model): capabilities a server
    # rejected once are remembered so later requests skip the failing probe.
    _vision_disabled: set[tuple[str, str]] = set()
    _stream_disabled: set[tuple[str, str]] = set()

    def __init__(
        self,
        api_config: ApiConfig | None,
        fallback: MockBarrageService | None = None,
        client: httpx.Client | None = None,
        on_item: Callable[[BarrageItem], None] | None = None,
    ) -> None:
        self._api_config = api_config
        self._fallback = fallback or MockBarrageService()
        self._client = client
        self._on_item = on_item

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

        # Concurrent generations share one pending GenerationRequest object;
        # work on a copy so stripping the image here doesn't mutate a request
        # another thread is serialising right now.
        request = replace(request)

        # Skip vision if this model is known to reject images
        vision_key = (self._api_config.base_url, self._api_config.model)
        if request.image_base64 and vision_key in self._vision_disabled:
            request.image_base64 = None

        # Streaming path: only for real HTTP clients (tests inject a fake
        # client with a plain .post) on the OpenAI protocol.
        use_stream = (
            self._client is None
            and self._api_config.protocol != "anthropic"
            and vision_key not in self._stream_disabled
        )
        if use_stream:
            result = self._generate_streaming(request, vision_key)
            if result is not None:
                return result
            # Stream path bowed out (unsupported server) — fall through to
            # the classic non-streaming request below.

        max_attempts = 1 + max(0, self._api_config.max_retries)

        for attempt in range(max_attempts):
            try:
                content = self._request_content(request)
                break
            except httpx.HTTPStatusError as http_exc:
                if request.image_base64 and http_exc.response.status_code in (400, 404, 422):
                    self._vision_disabled.add(vision_key)
                    logger.info("视觉请求不被模型支持（已记住），回退纯文本重试")
                    request.image_base64 = None
                    try:
                        content = self._request_content(request)
                        break
                    except Exception as exc:
                        logger.warning("纯文本重试也失败: %s", exc)
                        fallback = self._fallback.generate(request)
                        fallback.error = "api_error_retry"
                        return fallback
                else:
                    logger.warning("API HTTP 错误 (attempt %d/%d): %s", attempt + 1, max_attempts, http_exc)
                    if attempt < max_attempts - 1:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    fallback = self._fallback.generate(request)
                    fallback.error = "api_error"
                    return fallback
            except (httpx.RequestError, json.JSONDecodeError, KeyError, IndexError) as exc:
                logger.warning("API 请求异常 (attempt %d/%d): %s", attempt + 1, max_attempts, exc)
                if attempt < max_attempts - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                fallback = self._fallback.generate(request)
                fallback.error = "api_error"
                return fallback

        items = self.parse_items(content, request)
        if not items:
            fallback = self._fallback.generate(request)
            fallback.error = "empty_ai_result"
            return fallback
        return GenerationResult(items=items, source="ai")

    # ── Streaming ────────────────────────────────────────────────────────

    def _generate_streaming(
        self, request: GenerationRequest, vision_key: tuple[str, str],
    ) -> GenerationResult | None:
        """Stream the completion, emitting items as their lines arrive.

        Returns None when the server appears not to support streaming, so the
        caller can retry the classic path.
        """
        collector = _StreamCollector(request, self._on_item)
        try:
            full_text = self._request_openai(request, collector=collector)
        except httpx.HTTPStatusError as http_exc:
            status = http_exc.response.status_code
            if request.image_base64 and status in (400, 404, 422):
                self._vision_disabled.add(vision_key)
                logger.info("视觉请求不被模型支持（已记住），回退纯文本流式重试")
                request.image_base64 = None
                return self._generate_streaming(request, vision_key)
            if status in (400, 404, 405, 422) and not collector.items:
                # Could be a server that rejects stream:true outright.
                self._stream_disabled.add(vision_key)
                logger.info("流式请求被拒 (HTTP %d)，改用整包模式", status)
                return None
            logger.warning("流式 API HTTP 错误: %s", http_exc)
            if collector.items:
                return GenerationResult(items=collector.items, source="ai", streamed=True)
            fallback = self._fallback.generate(request)
            fallback.error = "api_error"
            return fallback
        except (httpx.RequestError, json.JSONDecodeError, KeyError, IndexError) as exc:
            # Connection died mid-stream: keep whatever already came through.
            logger.warning("流式请求异常: %s", exc)
            if collector.items:
                return GenerationResult(items=collector.items, source="ai", streamed=True)
            fallback = self._fallback.generate(request)
            fallback.error = "api_error"
            return fallback

        # Safety net: re-parse the full text and deliver anything the line
        # parser missed (e.g. the model ignored JSONL and sent one array).
        for item in self.parse_items(full_text, request):
            collector.add_parsed(item)

        if not collector.items:
            fallback = self._fallback.generate(request)
            fallback.error = "empty_ai_result"
            return fallback
        return GenerationResult(items=collector.items, source="ai", streamed=True)

    def parse_items(self, content: str, request: GenerationRequest) -> list[BarrageItem]:
        parsed = self._parse_json_array(content)
        raw_items: list[dict[str, Any]] = []
        if isinstance(parsed, list):
            raw_items = [item for item in parsed if isinstance(item, dict)]
        else:
            # JSONL / free text: try each line as a JSON object first, then
            # fall back to treating the line itself as barrage text.
            for line in self._lines_from_text(content):
                obj = _parse_line_object(line)
                if obj is not None:
                    raw_items.append(obj)
                elif not _looks_like_json_noise(line):
                    raw_items.append({"text": line})

        now = time.time()
        items: list[BarrageItem] = []
        seen_texts: set[str] = set()
        allowed_personas = set(request.personas or DEFAULT_PERSONAS)

        for raw in raw_items:
            item = _build_item(raw, request, allowed_personas, seen_texts, now)
            if item is not None:
                items.append(item)
            if len(items) >= request.count:
                break
        return items

    def _request_content(self, request: GenerationRequest) -> str:
        assert self._api_config is not None
        is_anthropic = self._api_config.protocol == "anthropic"

        if is_anthropic:
            return self._request_anthropic(request)
        return self._request_openai(request)

    # ── OpenAI protocol ─────────────────────────────────────────────────

    def _request_openai(
        self, request: GenerationRequest, collector: "_StreamCollector | None" = None,
    ) -> str:
        assert self._api_config is not None
        url = self._api_config.base_url.rstrip("/") + "/chat/completions"

        user_content: str | list[dict[str, Any]]
        if request.image_base64:
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

        # MiMo requires thinking:disabled — otherwise returns empty reasoning_content
        if "xiaomimimo.com" in url:
            payload["thinking"] = {"type": "disabled"}

        headers = {"Content-Type": "application/json"}
        if self._api_config.api_key:
            headers["Authorization"] = f"Bearer {self._api_config.api_key}"

        user_text = user_content if isinstance(user_content, str) else (
            next((b["text"] for b in user_content if isinstance(b, dict) and b.get("type") == "text"), "")
        )
        self._log_request(url, len(user_text), bool(request.image_base64))

        if collector is not None:
            payload["stream"] = True
            return self._stream_post(url, headers, payload, collector)

        def _do_post(client: httpx.Client) -> str:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content = str(data["choices"][0]["message"]["content"])
            try:
                self._log_response(response.status_code, content)
            except Exception:
                pass  # mock client may not expose status_code
            return content

        return self._exec_request(_do_post)

    def _stream_post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        collector: "_StreamCollector",
    ) -> str:
        """POST with SSE streaming; feed delta text to *collector* as it lands."""
        assert self._api_config is not None
        read_timeout = max(30.0, self._api_config.timeout_seconds)
        # ``read`` applies between chunks on a stream, not to the whole body.
        timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=10.0, pool=10.0)
        t0 = time.time()
        first_token_s: float | None = None

        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line or not raw_line.startswith("data:"):
                        continue
                    data = raw_line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        choices = chunk.get("choices") or []
                        delta = (choices[0].get("delta") or {}) if choices else {}
                        piece = delta.get("content")
                    except (json.JSONDecodeError, AttributeError, IndexError):
                        continue
                    if piece:
                        if first_token_s is None:
                            first_token_s = time.time() - t0
                        collector.feed(piece)

        collector.flush()
        logger.info(
            "[流式响应] 首字≈%.1fs | 总耗时=%.1fs | 边生成边解析=%d条",
            first_token_s if first_token_s is not None else -1.0,
            time.time() - t0,
            len(collector.items),
        )
        return collector.full_text

    # ── Anthropic protocol ──────────────────────────────────────────────

    def _request_anthropic(self, request: GenerationRequest) -> str:
        assert self._api_config is not None
        base = self._api_config.base_url.rstrip("/")
        # Standard Anthropic: base_url = https://api.anthropic.com → /v1/messages
        # MiMo-style:        base_url = .../anthropic           → /messages
        if base.endswith("/v1") or "/anthropic" in base:
            url = base + "/messages"
        else:
            url = base + "/v1/messages"

        user_blocks: list[dict[str, Any]] = []
        if request.image_base64:
            user_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": request.image_base64,
                },
            })
        user_blocks.append({"type": "text", "text": self._user_prompt(request)})

        payload: dict[str, Any] = {
            "model": self._api_config.model,
            "max_tokens": 256,
            "system": self._system_prompt(request),
            "messages": [{"role": "user", "content": user_blocks}],
            "temperature": 0.8,
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_config.api_key,
            "anthropic-version": "2023-06-01",
        }

        user_text = next((b["text"] for b in user_blocks if b.get("type") == "text"), "")
        self._log_request(url, len(user_text), bool(request.image_base64))

        def _do_post(client: httpx.Client) -> str:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content = str(data["content"][0]["text"])
            try:
                self._log_response(response.status_code, content)
            except Exception:
                pass  # mock client may not expose status_code
            return content

        return self._exec_request(_do_post)

    # ── Shared helpers ───────────────────────────────────────────────────

    def _exec_request(self, do_post) -> str:
        if self._client is not None:
            return do_post(self._client)
        read_timeout = max(30.0, self._api_config.timeout_seconds)
        timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=10.0, pool=10.0)
        with httpx.Client(timeout=timeout) as client:
            return do_post(client)

    def _log_request(self, url: str, prompt_len: int, has_image: bool) -> None:
        try:
            logger.info(
                "[HTTP 请求] %s | model=%s | prompt_len=%d | image=%s",
                url, self._api_config.model, prompt_len,
                "YES" if has_image else "NO",
            )
        except Exception:
            pass

    @staticmethod
    def _log_response(status_code: int, content: str) -> None:
        try:
            logger.info(
                "[HTTP 响应] status=%d | content_len=%d | preview=%.120s",
                status_code, len(content), content,
            )
        except Exception:
            pass  # graceful with mock/test clients

    @staticmethod
    def _system_prompt(request: GenerationRequest) -> str:
        # JSONL, one object per line: each line parses independently, so the
        # streaming path can put barrages on screen while the rest generate.
        base = (
            "你是直播间观众。每行输出一个 JSON 对象，"
            '形如 {"persona":"fun","text":"有点意思"}，'
            "不要输出数组、markdown 代码块或任何其他文字。"
            "每条弹幕 1 到 12 个中文字符，不要脏话、人身攻击或隐私内容。"
            "生成的弹幕要有不同人格的多样性，避免重复或相似的表达。"
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
            '输出格式: 每行一个 {"persona":"...","text":"..."}',
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
