"""Screen capture implementation using mss."""

from __future__ import annotations

import time
from typing import Any

import mss

from app.models import CapturedFrame


class MssScreenCapture:
    """Capture the primary monitor without saving images to disk."""

    def __init__(self, monitor_index: int = 1) -> None:
        self._monitor_index = monitor_index

    def capture(self) -> CapturedFrame:
        capture_factory = getattr(mss, "MSS", mss.mss)
        with capture_factory() as sct:
            monitor = sct.monitors[min(self._monitor_index, len(sct.monitors) - 1)]
            shot = sct.grab(monitor)

        return CapturedFrame(
            width=shot.width,
            height=shot.height,
            timestamp=time.time(),
            image=shot,
        )
