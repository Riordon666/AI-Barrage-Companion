"""Application entry point for AI Barrage Companion."""

from __future__ import annotations

from app.constants import APP_NAME
from app.models import AppSettings


def main() -> int:
    settings = AppSettings()
    print(f"{APP_NAME} scaffold ready")
    print(f"density={settings.density}, cost_mode={settings.cost_mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
