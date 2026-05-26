"""Local JSON settings persistence."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.config.settings import default_settings
from app.constants import (
    DEFAULT_BARRAGE_FONT_SIZE,
    DEFAULT_DISPLAY_AREA_PERCENT,
    DEFAULT_SETTINGS_FILENAME,
)
from app.config.provider_presets import provider_for_key
from app.models import ApiConfig, AppSettings, CostMode, Density, PrivacyMode


VALID_DENSITIES = {"low", "medium", "high"}
VALID_COST_MODES = {"immersive", "balanced", "saving"}
VALID_PRIVACY_MODES = {"strict", "balanced"}


class SettingsStore:
    """Read and write settings without exposing API keys in errors."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else Path(DEFAULT_SETTINGS_FILENAME)

    def load(self) -> tuple[AppSettings, str | None]:
        if not self.path.exists():
            return default_settings(), None

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return self._settings_from_dict(raw), None
        except Exception:
            return default_settings(), "配置文件损坏，已回退默认配置"

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(settings)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _settings_from_dict(self, raw: dict[str, Any]) -> AppSettings:
        api_raw = raw.get("api")
        api = None
        if isinstance(api_raw, dict):
            provider = str(api_raw.get("provider", "custom"))
            preset = provider_for_key(provider)
            api = ApiConfig(
                provider=provider,
                base_url=str(api_raw.get("base_url", preset.base_url)),
                api_key=str(api_raw.get("api_key", "")),
                model=str(api_raw.get("model", preset.models[0])),
                timeout_seconds=float(api_raw.get("timeout_seconds", 20.0)),
                max_retries=max(0, int(api_raw.get("max_retries", 1))),
            )

        density = raw.get("density", "medium")
        if density not in VALID_DENSITIES:
            density = "medium"

        cost_mode = raw.get("cost_mode", "balanced")
        if cost_mode not in VALID_COST_MODES:
            cost_mode = "balanced"

        privacy_mode = raw.get("privacy_mode", "strict")
        if privacy_mode not in VALID_PRIVACY_MODES:
            privacy_mode = "strict"

        return AppSettings(
            capture_interval_seconds=max(
                0.5,
                float(raw.get("capture_interval_seconds", 4.0)),
            ),
            density=density,  # type: ignore[arg-type]
            cost_mode=cost_mode,  # type: ignore[arg-type]
            api=api,
            use_mock_when_api_missing=bool(raw.get("use_mock_when_api_missing", True)),
            privacy_mode=privacy_mode,  # type: ignore[arg-type]
            enable_ocr=bool(raw.get("enable_ocr", False)),
            enable_window_title=bool(raw.get("enable_window_title", False)),
            display_area_percent=self._clamp_int(
                raw.get("display_area_percent", DEFAULT_DISPLAY_AREA_PERCENT),
                0,
                100,
            ),
            barrage_font_size=self._clamp_int(
                raw.get("barrage_font_size", DEFAULT_BARRAGE_FONT_SIZE),
                12,
                48,
            ),
        )

    @staticmethod
    def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = minimum
        return max(minimum, min(maximum, parsed))
