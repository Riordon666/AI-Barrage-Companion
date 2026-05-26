"""Default settings helpers."""

from __future__ import annotations

from app.constants import (
    DEFAULT_BARRAGE_FONT_SIZE,
    DEFAULT_CAPTURE_INTERVAL_SECONDS,
    DEFAULT_DISPLAY_AREA_PERCENT,
)
from app.models import AppSettings


def default_settings() -> AppSettings:
    """Return fresh default application settings."""

    return AppSettings(
        capture_interval_seconds=DEFAULT_CAPTURE_INTERVAL_SECONDS,
        display_area_percent=DEFAULT_DISPLAY_AREA_PERCENT,
        barrage_font_size=DEFAULT_BARRAGE_FONT_SIZE,
    )
