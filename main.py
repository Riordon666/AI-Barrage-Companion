"""Application entry point for AI Barrage Companion."""

from __future__ import annotations

from app.constants import APP_NAME
from app.core.barrage_manager import BasicBarrageManager
from app.core.mock_barrage_service import DEFAULT_PERSONAS, MockBarrageService
from app.core.privacy_guard import BasicPrivacyGuard
from app.models import AppSettings, GenerationRequest, SceneSummary


def main() -> int:
    settings = AppSettings()
    scene = SceneSummary(
        activity="active",
        pace="fast",
        event="highlight",
        confidence=0.9,
    )
    privacy_decision = BasicPrivacyGuard().sanitize(scene, settings)
    generator = MockBarrageService()
    generation = generator.generate(
        GenerationRequest(
            scene=privacy_decision.sanitized_scene,
            density=settings.density,
            personas=DEFAULT_PERSONAS,
            count=3,
        )
    )
    manager = BasicBarrageManager(density=settings.density)
    manager.enqueue(generation.items)
    assignments = manager.tick(
        now=0.0,
        viewport_width=1280,
        viewport_height=720,
    )

    print(f"{APP_NAME} scaffold ready")
    print(f"density={settings.density}, cost_mode={settings.cost_mode}")
    print(f"privacy_allowed={privacy_decision.allowed}")
    print(f"mock_barrages={len(generation.items)}")
    print(
        "scheduled_tracks="
        + ", ".join(str(assignment.track_index) for assignment in assignments)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
