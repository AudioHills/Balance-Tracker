"""Application log.

The desktop app is a windowed .exe with no console, so warnings and unexpected errors go to
``balance-tracker.log`` in the data folder (rotated, a few hundred KB at most). Reminder activity
the user can see in the app is kept separately in ``reminders.log`` (see notify.py).
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = "balance-tracker.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(folder: Path, level: int = logging.INFO) -> Path | None:
    """Send the app's log records to a file in `folder`. Safe to call more than once."""
    logger = logging.getLogger("balance_tracker")
    logger.setLevel(level)
    path = Path(folder) / LOG_FILE
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == path.resolve():
            return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=256_000, backupCount=2, encoding="utf-8")
    except OSError:
        return None  # read-only or missing data folder: run without a log file
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    return path
