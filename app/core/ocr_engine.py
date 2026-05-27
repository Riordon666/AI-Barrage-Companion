"""Screen OCR engine — extract readable text from captured frames.

Uses Windows 10/11 built-in OCR engine first (zero install), falling back to
Tesseract OCR via pytesseract when the Windows engine is unavailable.

Privacy note: OCR text is only extracted when the user has explicitly enabled
``enable_ocr`` in settings.  Text is truncated to 300 chars before sending.
"""

from __future__ import annotations

import hashlib
import io as _io
import logging
import re

from app.models import CapturedFrame

logger = logging.getLogger("abc.ocr")

_MAX_OCR_CHARS = 300  # safety cap per frame


# ---------------------------------------------------------------------------
# Image conversion helpers (reuse same logic as ai_service.encode_frame_*)
# ---------------------------------------------------------------------------

def _frame_to_pil(frame: CapturedFrame) -> "Image.Image | None":
    """Convert an mss CapturedFrame to a PIL Image in RGB."""
    from PIL import Image

    raw = _raw_bytes(frame.image)
    if not raw:
        return None
    bpp = max(1, len(raw) // max(1, frame.width * frame.height))
    if bpp >= 3:
        return Image.frombuffer(
            "RGB", (frame.width, frame.height), raw, "raw", _mss_raw_mode(),
        )
    return Image.frombuffer("L", (frame.width, frame.height), raw, "raw", "L")


def _mss_raw_mode() -> str:
    import sys

    return "BGRX" if sys.platform == "win32" else "BGRA"


def _raw_bytes(image: object) -> bytes:
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


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

_tesseract_available: bool | None = None  # None = not checked yet


def _check_tesseract() -> bool:
    """Return True if Tesseract-OCR is installed and the Chinese language
    pack is available."""
    global _tesseract_available
    if _tesseract_available is not None:
        return _tesseract_available

    try:
        import pytesseract  # noqa: F401  (side-effect: import test)
    except ImportError:
        logger.info("pytesseract 未安装 – OCR 不可用 (pip install pytesseract)")
        _tesseract_available = False
        return False

    try:
        langs = pytesseract.get_languages()
    except Exception:
        logger.info(
            "Tesseract-OCR 未安装或不在 PATH 中，"
            "请下载 https://github.com/UB-Mannheim/tesseract/wiki"
        )
        _tesseract_available = False
        return False

    if "chi_sim" not in langs:
        logger.info("Tesseract 缺少中文语言包 (chi_sim) – OCR 仅支持英文")
    _tesseract_available = True
    return True


def _hash_text(text: str) -> str:
    """Short hash to detect repeated / unchanged OCR results."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _windows_ocr(pil_image: "Image.Image") -> str:
    """Use Windows 10/11 built-in OCR engine."""
    from PIL import Image

    try:
        import winrt.windows.media.ocr as wocr  # type: ignore[no-redef]
        import winrt.windows.graphics.imaging as imaging  # type: ignore[no-redef]
        import winrt.windows.storage.streams as streams  # type: ignore[no-redef]
    except ImportError:
        return ""

    try:
        engine = wocr.OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return ""

        # Scale down — Windows OCR handles ~1024px best
        w, h = pil_image.size
        if w > 1200:
            s = 1024.0 / w
            pil_image = pil_image.resize((int(w * s), int(h * s)), Image.Resampling.LANCZOS)

        buf = _io.BytesIO()
        pil_image.save(buf, format="PNG")
        data = buf.getvalue()

        stream = streams.InMemoryRandomAccessStream()
        writer = streams.DataWriter(stream.get_output_stream_at(0))
        writer.write_bytes(data)
        writer.store_async().get()
        stream.seek(0)

        decoder = imaging.BitmapDecoder.create_async(stream).get()
        bitmap = decoder.get_software_bitmap_async().get()

        result = engine.recognize_async(bitmap).get()
        lines = [line.text for line in result.lines]
        return " ".join(lines)
    except Exception as exc:
        logger.info("Windows OCR 异常 (%s)", type(exc).__name__)
        return ""


def extract_screen_text(frame: CapturedFrame) -> str:
    """Run OCR on a captured frame and return cleaned text.

    Tries Windows built-in OCR first (no install needed), then Tesseract.
    Returns an empty string when OCR is unavailable.
    """
    pil_image = _frame_to_pil(frame)
    if pil_image is None:
        logger.info("OCR: 截图转换失败（raw bytes 为空）")
        return ""

    # --- Try Windows OCR first ---
    text = _windows_ocr(pil_image)
    cleaned = _clean_ocr_text(text) if text else ""
    if cleaned.strip():
        logger.info("Windows OCR 识别 %d 字符", len(cleaned))
        return cleaned

    if text and not cleaned.strip():
        logger.info("Windows OCR 识别到文字但清洗后为空（原始 %d 字符）", len(text))

    # --- Fall back to Tesseract ---
    if not _check_tesseract():
        return ""

    try:
        import pytesseract

        langs = "chi_sim+eng"
        text = pytesseract.image_to_string(pil_image, lang=langs, timeout=5)
    except Exception as exc:
        logger.info("Tesseract OCR 失败: %s", exc)
        return ""

    return _clean_ocr_text(text)


def _clean_ocr_text(raw: str) -> str:
    """Normalise OCR output: strip noise, compact whitespace, truncate."""
    # Remove very short lines (usually OCR noise)
    lines = [line.strip() for line in raw.splitlines() if len(line.strip()) >= 2]
    text = " | ".join(lines)
    # Collapse repeated whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _MAX_OCR_CHARS:
        text = text[:_MAX_OCR_CHARS] + "…"
    return text


class OcrCache:
    """Avoid sending identical OCR text to the AI on consecutive frames."""

    def __init__(self) -> None:
        self._last_hash: str = ""
        self._streak: int = 0  # consecutive same results

    def should_send(self, text: str) -> bool:
        """Return True only when the OCR text is different from last time."""
        if not text:
            return False
        h = _hash_text(text)
        if h == self._last_hash:
            self._streak += 1
            # Still resend every 10th identical frame to catch small changes
            return self._streak % 10 == 0
        self._last_hash = h
        self._streak = 0
        return True
