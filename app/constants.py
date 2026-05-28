"""Shared application constants."""

APP_NAME = "AI Barrage Companion"
APP_SHORT_NAME = "ABC"
DEFAULT_CAPTURE_INTERVAL_SECONDS = 4.0
DEFAULT_BARRAGE_DURATION_SECONDS = 8.0
DEFAULT_API_TIMEOUT_SECONDS = 20.0
DEFAULT_DUPLICATE_WINDOW_SECONDS = 10.0
DEFAULT_MIN_BARRAGE_SPEED = 80.0
DEFAULT_TRACK_HEIGHT = 36
DEFAULT_TRACK_GAP = 12
DEFAULT_SETTINGS_FILENAME = "abc-settings.json"
DEFAULT_AI_BARRAGE_COUNT = 30
DEFAULT_RENDER_TICK_MS = 100
DEFAULT_BARRAGE_BUFFER_LIMIT = 120
DEFAULT_DISPLAY_AREA_PERCENT = 65
DEFAULT_BARRAGE_FONT_SIZE = 18

# Density → (min_ms, max_ms) send interval for normal scenes.
DENSITY_SEND_INTERVAL = {
    "low": (667, 2000),    # 0.5–1.5 barrages/sec
    "medium": (333, 1000),  # 1–3 barrages/sec
    "high": (167, 500),     # 2–6 barrages/sec
}

# Density → (min_ms, max_ms) send interval for highlight / burst scenes.
DENSITY_HIGHLIGHT_INTERVAL = {
    "low": (250, 1000),
    "medium": (125, 500),
    "high": (60, 250),
}

# Burst gap divisor: track gap is divided by this value during highlights.
HIGHLIGHT_GAP_DIVISOR = 3

# Persona → speed multiplier for barrage duration (lower = faster).
PERSONA_SPEED: dict[str, float] = {
    "troll": 0.85,
    "support": 0.95,
    "sarcastic": 1.05,
    "follower": 0.90,
    "fun": 0.95,
}
