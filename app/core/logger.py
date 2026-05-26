"""Application logging with Qt signal bridge for UI display."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

LOG_DIR = Path.home() / ".abc" / "logs"
LOG_FILE = LOG_DIR / "abc.log"
LOG_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
LOG_BACKUP_COUNT = 3


class LogEmitter(QObject):
    """Bridge Python log records to Qt signals so the UI can display them."""

    newLog = Signal(str)  # formatted log line


# Module-level singleton: never construct LogEmitter again after first use.
_log_emitter: LogEmitter | None = None


def _get_emitter() -> LogEmitter:
    global _log_emitter
    if _log_emitter is None:
        _log_emitter = LogEmitter()
    return _log_emitter


class _UiHandler(logging.Handler):
    """Logging handler that emits records through the LogEmitter signal."""

    def __init__(self, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))

    def emit(self, record: logging.Record) -> None:
        try:
            msg = self.format(record)
            _get_emitter().newLog.emit(msg)
        except Exception:
            self.handleError(record)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure rotating file + console + Qt signal logging."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("abc")
    root.setLevel(level)
    root.handlers.clear()

    # File handler with rotation
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"),
    )
    root.addHandler(file_handler)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root.addHandler(console)

    # Qt signal handler
    ui_handler = _UiHandler(level)
    root.addHandler(ui_handler)


def get_emitter() -> LogEmitter:
    """Return the module-level LogEmitter singleton (thread-safe by GIL)."""
    return _get_emitter()


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``abc`` namespace."""
    return logging.getLogger(f"abc.{name}")
