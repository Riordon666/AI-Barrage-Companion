"""Animation helpers shared by the control panel.

Two rules hold everywhere in this module:

* every animation is parented and started with ``DeleteWhenStopped``, so no
  caller has to keep a reference alive to stop it being garbage collected;
* nothing here runs on a timer while it is idle — animations exist only for
  the duration of the transition they describe.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRect,
    Qt,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from app.ui.theme import DUR_BASE, EASE_OUT

_DELETE_WHEN_STOPPED = QAbstractAnimation.DeletionPolicy.DeleteWhenStopped


def stop_safely(anim: QPropertyAnimation | None) -> None:
    """Stop an animation that may already have finished and self-deleted.

    Everything from :func:`animate` uses ``DeleteWhenStopped``, so by the time
    a caller wants to cancel, the C++ object may be gone; ``shiboken6.isValid``
    is the supported way to check before touching it.
    """
    if anim is None:
        return
    import shiboken6

    if shiboken6.isValid(anim):
        anim.stop()


def animate(
    target: QObject,
    prop: bytes,
    end_value,
    *,
    start_value=None,
    duration: int = DUR_BASE,
    easing: QEasingCurve.Type = EASE_OUT,
    on_finish: Callable[[], None] | None = None,
) -> QPropertyAnimation:
    """Animate *prop* on *target* to *end_value* and start it immediately."""
    anim = QPropertyAnimation(target, prop, target)
    anim.setDuration(duration)
    anim.setStartValue(target.property(prop.decode()) if start_value is None else start_value)
    anim.setEndValue(end_value)
    anim.setEasingCurve(easing)
    if on_finish is not None:
        anim.finished.connect(on_finish)
    anim.start(_DELETE_WHEN_STOPPED)
    return anim


def animate_geometry(
    widget: QWidget,
    end_rect: QRect,
    *,
    duration: int = DUR_BASE,
    easing: QEasingCurve.Type = EASE_OUT,
) -> QPropertyAnimation:
    """Slide/resize *widget* into *end_rect*."""
    return animate(
        widget, b"geometry", end_rect,
        start_value=widget.geometry(), duration=duration, easing=easing,
    )


def fade_out(
    widget: QWidget,
    *,
    duration: int = DUR_BASE,
    easing: QEasingCurve.Type = EASE_OUT,
    on_finish: Callable[[], None] | None = None,
) -> QPropertyAnimation:
    """Fade *widget* to fully transparent via a graphics opacity effect."""
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(1.0)
    return animate(
        effect, b"opacity", 0.0,
        start_value=1.0, duration=duration, easing=easing, on_finish=on_finish,
    )


class SnapshotFader(QLabel):
    """Cross-fades page changes inside a container.

    The outgoing page is grabbed into a pixmap and that still image is faded
    out on top of the new page.  Only the snapshot carries a graphics effect,
    so the live page never pays for offscreen rendering — which matters here
    because the pages themselves are full of drop-shadowed cards.
    """

    def __init__(self, container: QWidget) -> None:
        super().__init__(container)
        self._container = container
        self._anim: QPropertyAnimation | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setScaledContents(False)
        self.hide()

    def capture(self) -> None:
        """Snapshot the container as it looks right now."""
        if self._container.width() <= 0 or self._container.height() <= 0:
            return
        # Abandon any fade still in flight first: this label is a child of the
        # container, so grabbing while it is visible would snapshot the
        # previous snapshot and the pages would smear into each other.
        self._cancel()
        self.setPixmap(self._container.grab())
        self.setGeometry(self._container.rect())
        self.raise_()
        self.show()

    def release(self, duration: int = DUR_BASE) -> None:
        """Fade the snapshot away, revealing whatever is underneath."""
        if not self.isVisible():
            return
        self._anim = fade_out(self, duration=duration, on_finish=self._done)

    def _cancel(self) -> None:
        stop_safely(self._anim)  # DeleteWhenStopped disposes of it
        self._anim = None
        self.setGraphicsEffect(None)  # type: ignore[arg-type]
        self.hide()

    def _done(self) -> None:
        self._anim = None
        self.hide()
        self.clear()
        # Drop the effect so the hidden label holds no offscreen buffer.
        self.setGraphicsEffect(None)  # type: ignore[arg-type]
