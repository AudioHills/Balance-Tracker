"""Run slow work (sending email, checking for updates) off the UI thread."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

log = logging.getLogger(__name__)

Callback = Callable[[Any, "Exception | None"], None]


class _Relay(QObject):
    """Lives on the UI thread; the worker emits `done` and Qt queues the callback onto the UI thread."""

    done = Signal(object, object)

    def __init__(self, parent: QObject, callback: Callback):
        super().__init__(parent)
        self._callback = callback
        self.done.connect(self._deliver)

    @Slot(object, object)
    def _deliver(self, result, error):
        try:
            self._callback(result, error)
        finally:
            self.deleteLater()


def run_in_background(parent: QObject, work: Callable[[], Any], callback: Callback) -> None:
    """Run `work()` on a worker thread, then call `callback(result, error)` on the UI thread.
    Exactly one of `result` / `error` is meaningful; `error` is None on success."""
    relay = _Relay(parent, callback)

    def target():
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001 - handed to the callback, never lost
            log.warning("Background task failed: %s", e, exc_info=True)
            result, error = None, e
        relay.done.emit(result, error)

    threading.Thread(target=target, daemon=True).start()
