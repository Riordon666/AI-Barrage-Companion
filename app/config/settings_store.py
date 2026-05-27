"""Local JSON settings persistence."""

from __future__ import annotations

import json
import logging
import os
import platform
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from app.config.settings import default_settings
from app.constants import (
    DEFAULT_BARRAGE_FONT_SIZE,
    DEFAULT_DISPLAY_AREA_PERCENT,
    DEFAULT_SETTINGS_FILENAME,
)
from app.config.provider_presets import provider_for_key
from app.core.utils import as_density, as_privacy_mode
from app.models import ApiConfig, AppSettings, CostMode, Density, PrivacyMode

logger = logging.getLogger("abc.settings")

VALID_DENSITIES = {"low", "medium", "high"}
VALID_COST_MODES = {"immersive", "balanced", "saving"}
VALID_PRIVACY_MODES = {"strict", "balanced"}

# --- Encryption helpers ---

_SECRET_DIR = Path.home() / ".abc"
_SECRET_KEY_FILE = _SECRET_DIR / ".secret_key"
_ENCRYPT_PREFIX = "enc:v1:"


def _get_fernet():
    """Return a Fernet instance, creating the key file if needed."""
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        import base64
    except ImportError:
        return None

    if _SECRET_KEY_FILE.exists():
        try:
            key = _SECRET_KEY_FILE.read_bytes().strip()
            return Fernet(key)
        except Exception:
            pass

    # Derive key from machine characteristics
    seed = f"{platform.node()}:{os.getenv('USERNAME', os.getenv('USER', 'abc'))}"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"abc-barrage-v1", iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(seed.encode()))
    try:
        _SECRET_DIR.mkdir(parents=True, exist_ok=True)
        _SECRET_KEY_FILE.write_bytes(key)
    except OSError:
        pass
    return Fernet(key)


def _encrypt_value(fernet, text: str) -> str:
    """Encrypt a string, returning prefixed ciphertext."""
    if not text:
        return text
    return _ENCRYPT_PREFIX + fernet.encrypt(text.encode()).decode()


def _decrypt_value(fernet, text: str) -> str:
    """Decrypt a prefixed ciphertext, returning plaintext."""
    if not text or not text.startswith(_ENCRYPT_PREFIX):
        return text  # Not encrypted (legacy plain text)
    try:
        return fernet.decrypt(text[len(_ENCRYPT_PREFIX):].encode()).decode()
    except Exception:
        return text  # Corrupted or wrong key


class SettingsStore:
    """Read and write settings without exposing API keys in errors."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else Path(DEFAULT_SETTINGS_FILENAME)
        self._fernet = _get_fernet()

    def load(self) -> tuple[AppSettings, str | None]:
        if not self.path.exists():
            return default_settings(), None

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return self._settings_from_dict(raw), None
        except (json.JSONDecodeError, OSError):
            return default_settings(), "配置文件损坏，已回退默认配置"

    def save(self, settings: AppSettings) -> None:
        data = asdict(settings)
        # Encrypt API keys before saving
        if self._fernet:
            if data.get("api") and data["api"].get("api_key"):
                data["api"]["api_key"] = _encrypt_value(self._fernet, data["api"]["api_key"])
            for entry in data.get("api_history", []):
                if isinstance(entry, dict) and entry.get("api_key"):
                    entry["api_key"] = _encrypt_value(self._fernet, entry["api_key"])
        json_text = json.dumps(data, ensure_ascii=False, indent=2)

        # Atomic write: write to temp file first, then rename to avoid partial/corrupt writes.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp_path.write_text(json_text, encoding="utf-8")
            tmp_path.replace(self.path)
        except OSError:
            # Disk full, permission denied, or filesystem error – fail silently
            # rather than crashing the application. Settings are still held
            # in-memory and can be saved on the next attempt.
            pass

    def _settings_from_dict(self, raw: dict[str, Any]) -> AppSettings:
        api_raw = raw.get("api")
        api = None
        if isinstance(api_raw, dict):
            provider = str(api_raw.get("provider", "custom"))
            preset = provider_for_key(provider)
            api = ApiConfig(
                provider=provider,
                base_url=str(api_raw.get("base_url", preset.base_url)),
                api_key=self._decrypt(str(api_raw.get("api_key", ""))),
                model=str(api_raw.get("model", preset.models[0])),
                timeout_seconds=float(api_raw.get("timeout_seconds", 60.0)),
                max_retries=max(0, int(api_raw.get("max_retries", 1))),
                protocol=str(api_raw.get("protocol", preset.protocol)),
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

        # API history
        api_history: list[ApiConfig] = []
        history_raw = raw.get("api_history")
        if isinstance(history_raw, list):
            for entry in history_raw:
                if isinstance(entry, dict):
                    hp = str(entry.get("provider", "custom"))
                    hp_preset = provider_for_key(hp)
                    api_history.append(ApiConfig(
                        provider=hp,
                        base_url=str(entry.get("base_url", hp_preset.base_url)),
                        api_key=self._decrypt(str(entry.get("api_key", ""))),
                        model=str(entry.get("model", hp_preset.models[0])),
                        timeout_seconds=float(entry.get("timeout_seconds", 60.0)),
                        max_retries=max(0, int(entry.get("max_retries", 1))),
                        protocol=str(entry.get("protocol", hp_preset.protocol)),
                    ))

        return AppSettings(
            capture_interval_seconds=max(
                0.5,
                float(raw.get("capture_interval_seconds", 4.0)),
            ),
            density=as_density(density),
            cost_mode=cast(CostMode, cost_mode),
            api=api,
            api_history=api_history,
            use_mock_when_api_missing=bool(raw.get("use_mock_when_api_missing", True)),
            privacy_mode=as_privacy_mode(privacy_mode),
            enable_ocr=bool(raw.get("enable_ocr", False)),
            enable_window_title=bool(raw.get("enable_window_title", False)),
            enable_vision=bool(raw.get("enable_vision", False)),
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

    def _decrypt(self, text: str) -> str:
        """Decrypt an API key value if Fernet is available."""
        if self._fernet:
            return _decrypt_value(self._fernet, text)
        return text

    @staticmethod
    def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = minimum
        return max(minimum, min(maximum, parsed))
