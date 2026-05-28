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
from dataclasses import dataclass

from app.models import CapturedFrame

logger = logging.getLogger("abc.ocr")

_MAX_OCR_CHARS = 800  # per-frame cap


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
_tesseract_status_message = ""
_windows_ocr_available: bool | None = None  # None = not checked yet


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str
    status: str
    message: str


def _get_bundled_dir() -> str:
    """Return the directory containing bundled tesseract.exe and tessdata/.

    When packaged with PyInstaller, sys._MEIPASS is the temp extraction dir.
    In dev mode, falls back to a ``tesseract/`` folder next to the project root.
    """
    import os
    import sys

    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "ocr")  # type: ignore[union-attr]

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(project_root, "ocr")


def _find_tesseract_cmd() -> str | None:
    """Try to locate tesseract.exe on Windows."""
    import shutil
    import os

    # 0) Bundled copy (PyInstaller / dev tesseract folder)
    bundled = os.path.join(_get_bundled_dir(), "tesseract.exe")
    if os.path.isfile(bundled):
        return bundled

    # 1) Already on PATH?
    found = shutil.which("tesseract")
    if found:
        return found

    # 2) Common install locations on Windows
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    # 3) Check TESSERACT_PREFIX env var
    prefix = os.environ.get("TESSERACT_PREFIX") or os.environ.get("TESSDATA_PREFIX")
    if prefix:
        exe = os.path.join(os.path.dirname(prefix), "tesseract.exe")
        if os.path.isfile(exe):
            return exe
        exe = os.path.join(prefix, "tesseract.exe")
        if os.path.isfile(exe):
            return exe

    return None


def _check_tesseract() -> tuple[bool, str]:
    """Return True if Tesseract-OCR is installed and the Chinese language
    pack is available."""
    global _tesseract_available, _tesseract_status_message
    if _tesseract_available is not None:
        return _tesseract_available, _tesseract_status_message

    try:
        import pytesseract  # noqa: F401  (side-effect: import test)
    except ImportError:
        message = "pytesseract 未安装 – OCR 不可用 (pip install pytesseract)"
        logger.info(message)
        _tesseract_available = False
        _tesseract_status_message = message
        return False, message

    # Auto-locate tesseract executable
    import os

    cmd = _find_tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
        logger.info("Tesseract 路径: %s", cmd)
        # Windows Tesseract (UB-Mannheim) treats TESSDATA_PREFIX as the
        # tessdata directory itself, not its parent
        tessdata = os.path.join(os.path.dirname(cmd), "tessdata")
        if os.path.isdir(tessdata):
            os.environ["TESSDATA_PREFIX"] = tessdata

    try:
        langs = pytesseract.get_languages()
    except Exception:
        message = (
            "Tesseract-OCR 未安装或不在 PATH 中，"
            "请下载 https://github.com/UB-Mannheim/tesseract/wiki"
        )
        logger.info(message)
        _tesseract_available = False
        _tesseract_status_message = message
        return False, message

    if "chi_sim" not in langs:
        _tesseract_status_message = "Tesseract 可用，但缺少中文语言包 (chi_sim)，OCR 仅支持英文"
        logger.info(_tesseract_status_message)
    else:
        _tesseract_status_message = "Tesseract OCR 可用"
    _tesseract_available = True
    return True, _tesseract_status_message


def _hash_text(text: str) -> str:
    """Short hash to detect repeated / unchanged OCR results."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _windows_ocr(pil_image: "Image.Image") -> str:
    """Use Windows 10/11 built-in OCR engine."""
    global _windows_ocr_available
    if _windows_ocr_available is False:
        return ""

    try:
        import winrt.windows.media.ocr as wocr  # type: ignore[no-redef]
        import winrt.windows.graphics.imaging as imaging  # type: ignore[no-redef]
        import winrt.windows.storage.streams as streams  # type: ignore[no-redef]
    except ImportError:
        _windows_ocr_available = False
        return ""

    from PIL import Image

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
        _windows_ocr_available = True
        return " ".join(lines)
    except RuntimeError as exc:
        _windows_ocr_available = False
        logger.info("Windows OCR 当前不可用，已改用 Tesseract 降级 (%s)", type(exc).__name__)
        return ""
    except Exception as exc:
        logger.info("Windows OCR 异常 (%s)", type(exc).__name__)
        return ""


def extract_screen_text_with_status(frame: CapturedFrame) -> OcrResult:
    """Run OCR and return text plus user-facing diagnostics."""
    pil_image = _frame_to_pil(frame)
    if pil_image is None:
        message = "截图转换失败（raw bytes 为空）"
        logger.info("OCR: %s", message)
        return OcrResult(text="", engine="none", status="image_error", message=message)

    # --- Try Windows OCR first ---
    text = _windows_ocr(pil_image)
    cleaned = _clean_ocr_text(text) if text else ""
    if cleaned.strip():
        logger.info("Windows OCR 识别 %d 字符", len(cleaned))
        return OcrResult(text=cleaned, engine="windows", status="ok", message="Windows OCR 识别成功")

    if text and not cleaned.strip():
        logger.info("Windows OCR 识别到文字但清洗后为空（原始 %d 字符）", len(text))

    # --- Fall back to Tesseract ---
    tesseract_ok, message = _check_tesseract()
    if not tesseract_ok:
        return OcrResult(text="", engine="tesseract", status="unavailable", message=message)

    try:
        import pytesseract

        langs = "chi_sim+eng"
        ocr_image = _prepare_for_tesseract(pil_image)
        text = pytesseract.image_to_string(
            ocr_image,
            lang=langs,
            config="--oem 3 --psm 11",
            timeout=8,
        )
    except Exception as exc:
        message = f"Tesseract OCR 失败: {exc}"
        logger.info(message)
        return OcrResult(text="", engine="tesseract", status="error", message=message)

    cleaned = _clean_ocr_text(text)
    if cleaned:
        logger.info("Tesseract OCR 识别 %d 字符", len(cleaned))
        return OcrResult(text=cleaned, engine="tesseract", status="ok", message="Tesseract OCR 识别成功")
    return OcrResult(text="", engine="tesseract", status="empty", message="OCR 后端可用，但当前画面未识别到文字")


def extract_screen_text(frame: CapturedFrame) -> str:
    """Run OCR on a captured frame and return cleaned text."""

    return extract_screen_text_with_status(frame).text


def _prepare_for_tesseract(pil_image: "Image.Image") -> "Image.Image":
    """Preprocess image for Tesseract OCR."""
    from PIL import Image, ImageFilter, ImageOps

    image = pil_image.convert("L")
    width, height = image.size
    # Downscale to max 1920px — preserves text readability
    max_dim = max(width, height)
    if max_dim > 1920:
        scale = 1920.0 / max_dim
        image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image, cutoff=2)
    image = image.filter(ImageFilter.SHARPEN)
    return image


def _clean_ocr_text(raw: str) -> str:
    """Normalise OCR output: strip noise, compact whitespace, truncate."""
    # Remove very short lines (usually OCR noise)
    lines = [line.strip() for line in raw.splitlines() if len(line.strip()) >= 2]
    text = " | ".join(lines)
    # Collapse repeated whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _MAX_OCR_CHARS:
        text = text[:_MAX_OCR_CHARS] + "…"
    # Quality check: if the result is mostly garbage, discard it
    if text and not _is_readable_text(text):
        return ""
    return text


def _is_readable_text(text: str) -> bool:
    """Return True if OCR result looks like readable text, not garbage."""
    total = len(text)
    if total == 0:
        return False

    # Check CJK character ratio — real Chinese content should have decent CJK
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    cjk_ratio = cjk / total

    # If there are enough CJK characters, it's likely real text
    if cjk_ratio >= 0.10:
        return True

    # For mostly-ASCII text, split into fragments and analyze
    fragments = re.split(r"[|,\s]+", text)
    fragments = [f for f in fragments if len(f) >= 2]
    if not fragments:
        return False

    # Count short fragments (2-3 chars) — OCR noise is mostly these
    short = sum(1 for f in fragments if len(f) <= 3)
    # If more than half the fragments are very short, it's garbage
    if len(fragments) >= 4 and short / len(fragments) > 0.50:
        return False

    return True


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
