"""Shared utilities used across core modules."""

from __future__ import annotations

from typing import cast

from app.models import Activity, CaptureReason, Density, Persona, PrivacyMode, SceneEvent


def raw_image_bytes(image: object) -> bytes:
    """Extract raw pixel bytes from an mss screenshot object (or bytes)."""
    if isinstance(image, bytes):
        return image
    if isinstance(image, bytearray):
        return bytes(image)
    raw = getattr(image, "raw", None)
    if isinstance(raw, bytes):
        return raw
    bgra = getattr(image, "bgra", None)
    if isinstance(bgra, bytes):
        return bgra
    rgb = getattr(image, "rgb", None)
    if isinstance(rgb, bytes):
        return rgb
    return b""


def priority_for_event(event: SceneEvent) -> int:
    """Return display priority for a scene event type."""
    if event == "highlight":
        return 10
    if event == "stuck":
        return 5
    return 0


# ---------------------------------------------------------------------------
# Type-narrowing helpers: these cast runtime-validated strings to their
# Literal types so the static type checker can track them precisely.
# ---------------------------------------------------------------------------

def as_activity(value: str) -> Activity:
    return cast(Activity, value)


def as_capture_reason(value: str) -> CaptureReason:
    return cast(CaptureReason, value)


def as_density(value: str) -> Density:
    return cast(Density, value)


def as_persona(value: str) -> Persona:
    return cast(Persona, value)


def as_privacy_mode(value: str) -> PrivacyMode:
    return cast(PrivacyMode, value)


def as_scene_event(value: str) -> SceneEvent:
    return cast(SceneEvent, value)
