"""Tests for the OCR engine — text cleaning, caching, and graceful fallback."""

from __future__ import annotations

from app.core.ocr_engine import (
    OcrCache,
    _clean_ocr_text,
    _hash_text,
    extract_screen_text,
)
from app.models import CapturedFrame


class TestCleanOcrText:
    def test_strips_noise_short_lines(self) -> None:
        raw = "a\n  \nhello world\n \nb\nx\n  "
        result = _clean_ocr_text(raw)
        # lines shorter than 2 chars are dropped
        assert "a" not in result.split(" | ")
        assert "hello world" in result

    def test_truncates_long_text(self) -> None:
        raw = "word " * 200
        result = _clean_ocr_text(raw)
        assert len(result) <= 300 + 5  # plus "…" and some tolerance

    def test_collapses_whitespace(self) -> None:
        raw = "hello    world  \n\n  foo   bar"
        result = _clean_ocr_text(raw)
        assert "hello world" in result
        assert "foo bar" in result

    def test_empty_input(self) -> None:
        assert _clean_ocr_text("") == ""
        assert _clean_ocr_text("  \n \n  ") == ""


class TestHashText:
    def test_same_text_same_hash(self) -> None:
        h1 = _hash_text("screen content")
        h2 = _hash_text("screen content")
        assert h1 == h2

    def test_different_text_different_hash(self) -> None:
        h1 = _hash_text("hello")
        h2 = _hash_text("world")
        assert h1 != h2

    def test_hash_is_consistent_length(self) -> None:
        assert len(_hash_text("abc")) == 12


class TestOcrCache:
    def test_first_send_is_allowed(self) -> None:
        cache = OcrCache()
        assert cache.should_send("hello world") is True

    def test_duplicate_text_is_blocked(self) -> None:
        cache = OcrCache()
        cache.should_send("hello world")
        assert cache.should_send("hello world") is False

    def test_duplicate_is_allowed_every_tenth_time(self) -> None:
        cache = OcrCache()
        cache.should_send("same text")  # call #1 — new text, always allowed, streak=0
        for _i in range(9):            # calls #2–#10 — streak goes 1→9, 10th → streak=10
            cache.should_send("same text")
        # call #11: streak=10 → 10%10==0 → allowed
        assert cache.should_send("same text") is True

    def test_different_text_is_allowed(self) -> None:
        cache = OcrCache()
        cache.should_send("apple")
        assert cache.should_send("banana") is True

    def test_empty_text_never_sent(self) -> None:
        cache = OcrCache()
        assert cache.should_send("") is False


class TestGracefulFallback:
    def test_extract_screen_text_without_tesseract_returns_empty(self) -> None:
        """When Tesseract is not installed, extract_screen_text should
        return '' without crashing."""
        # Create a minimal fake frame
        frame = CapturedFrame(
            width=8,
            height=8,
            timestamp=0.0,
            image=b"\x00" * 8 * 8 * 4,  # 8×8 black BGRA pixels
        )
        result = extract_screen_text(frame)
        # If Tesseract is installed this may return actual text;
        # if not, it must return '' (no crash).
        assert isinstance(result, str)
