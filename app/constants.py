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
DEFAULT_AI_BARRAGE_COUNT = 3
DEFAULT_RENDER_TICK_MS = 100
DEFAULT_BARRAGE_BUFFER_LIMIT = 10
DEFAULT_DISPLAY_AREA_PERCENT = 65
DEFAULT_BARRAGE_FONT_SIZE = 18

# Density → (min_ms, max_ms) send interval for normal scenes.
DENSITY_SEND_INTERVAL = {
    "low": (800, 3500),
    "medium": (400, 2000),
    "high": (200, 1200),
}

# Density → (min_ms, max_ms) send interval for highlight / burst scenes.
DENSITY_HIGHLIGHT_INTERVAL = {
    "low": (300, 1500),
    "medium": (150, 800),
    "high": (80, 400),
}

# Burst gap divisor: track gap is divided by this value during highlights.
HIGHLIGHT_GAP_DIVISOR = 3

# Persona → speed multiplier for barrage duration (lower = faster).
PERSONA_SPEED: dict[str, float] = {
    "troll": 0.65,
    "support": 0.9,
    "sarcastic": 1.2,
    "follower": 0.75,
    "fun": 0.9,
}
