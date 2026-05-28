"""Supported OpenAI-compatible provider presets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    label: str
    base_url: str
    models: tuple[str, ...]
    requires_api_key: bool = True
    protocol: str = "openai"  # "openai" | "anthropic"


SUPPORTED_PROVIDERS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        models=("gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"),
    ),
    ProviderPreset(
        key="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        models=("deepseek-chat", "deepseek-reasoner"),
    ),
    ProviderPreset(
        key="qwen",
        label="阿里云百炼 / Qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=("qwen-plus", "qwen-turbo", "qwen-max"),
    ),
    ProviderPreset(
        key="moonshot",
        label="Moonshot / Kimi",
        base_url="https://api.moonshot.cn/v1",
        models=("moonshot-v1-8k", "moonshot-v1-32k", "kimi-latest"),
    ),
    ProviderPreset(
        key="zhipu",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        models=("glm-4-flash", "glm-4-plus", "glm-4-air"),
    ),
    ProviderPreset(
        key="siliconflow",
        label="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        models=(
            "Qwen/Qwen2.5-7B-Instruct",
            "deepseek-ai/DeepSeek-V3",
            "moonshotai/Kimi-K2-Instruct",
        ),
    ),
    ProviderPreset(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        models=(
            "openai/gpt-4.1-mini",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.0-flash-001",
        ),
    ),
    ProviderPreset(
        key="ollama",
        label="Ollama 本地",
        base_url="http://localhost:11434/v1",
        models=("qwen2.5:7b", "llama3.1:8b", "gemma2:9b"),
        requires_api_key=False,
    ),
    ProviderPreset(
        key="mimo",
        label="小米 MiMo",
        base_url="https://api.xiaomimimo.com/v1",
        models=("mimo-v2.5", "mimo-v2-omni"),
        protocol="openai",
    ),
    ProviderPreset(
        key="custom",
        label="自定义 OpenAI 兼容",
        base_url="",
        models=("custom-model",),
        requires_api_key=False,
    ),
)


PROVIDER_BY_KEY = {provider.key: provider for provider in SUPPORTED_PROVIDERS}


def provider_for_key(key: str) -> ProviderPreset:
    return PROVIDER_BY_KEY.get(key, PROVIDER_BY_KEY["custom"])
