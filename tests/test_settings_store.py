from pathlib import Path

from app.config.settings_store import SettingsStore
from app.models import ApiConfig, AppSettings


def test_settings_store_uses_defaults_when_file_is_missing(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "missing.json")

    settings, warning = store.load()

    assert warning is None
    assert settings.density == "medium"
    assert settings.use_mock_when_api_missing is True


def test_settings_store_round_trips_api_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    original = AppSettings(
        density="high",
        display_area_percent=42,
        barrage_font_size=24,
        api=ApiConfig(
            provider="deepseek",
            base_url="https://api.example.test/v1",
            api_key="secret",
            model="chat",
        ),
    )

    store.save(original)
    loaded, warning = store.load()

    assert warning is None
    assert loaded.density == "high"
    assert loaded.api is not None
    assert loaded.api.api_key == "secret"
    assert loaded.api.model == "chat"
    assert loaded.display_area_percent == 42
    assert loaded.barrage_font_size == 24


def test_settings_store_clamps_display_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        '{"display_area_percent": 120, "barrage_font_size": 4}',
        encoding="utf-8",
    )

    settings, warning = SettingsStore(path).load()

    assert warning is None
    assert settings.display_area_percent == 100
    assert settings.barrage_font_size == 12


def test_settings_store_recovers_from_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")

    settings, warning = SettingsStore(path).load()

    assert settings.density == "medium"
    assert warning is not None
