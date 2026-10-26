"""Application entry point."""
from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__, applock, logs, storage
from .models import AppData
from .ui import theme
from .ui.dialogs import LockScreen
from .ui.icon import app_icon
from .ui.main_window import MainWindow

log = logging.getLogger(__name__)


def _load(store: storage.Store) -> AppData:
    """Load the data file, offering the latest automatic backup if it's damaged."""
    try:
        return store.load()
    except Exception as e:  # noqa: BLE001 - corrupt or unreadable data file
        log.error("Couldn't open %s: %s", store.path, e)
        backups = store.auto_backups()
        text = f"Your data file couldn't be opened:\n{e}"
        if backups:
            ans = QMessageBox.question(None, "Balance Tracker",
                                       text + f"\n\nRestore the most recent automatic backup ({backups[0].stem})?")
            if ans == QMessageBox.Yes:
                return storage.read_backup(backups[0])
        QMessageBox.critical(None, "Balance Tracker", text + f"\n\nThe file is at {store.path}.")
        sys.exit(1)


def _install_error_handler(store: storage.Store) -> None:
    """A windowed app has no console: log unexpected errors and tell the user instead of failing silently."""
    def handler(kind, value, tb):
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, tb)
            return
        log.critical("Unexpected error:\n%s", "".join(traceback.format_exception(kind, value, tb)))
        QMessageBox.warning(None, "Balance Tracker",
                            f"Something went wrong: {value}\n\nYour data is safe. Details were written to "
                            f"{store.folder / logs.LOG_FILE} — please include them if you report the problem.")
    sys.excepthook = handler


def _send_reminders() -> int:
    """Run by Windows Task Scheduler (`--send-reminders`): send today's digest, no window."""
    from . import notify
    store = storage.Store()
    logs.setup(store.folder)
    try:
        notify.run_daily(store)
    except Exception as e:  # noqa: BLE001 - never crash a background task
        log.exception("Reminder run failed")
        notify.log_activity(store.folder, f"error: {e}")
        return 1
    return 0


def main() -> int:
    if "--send-reminders" in sys.argv:
        return _send_reminders()
    if sys.platform == "win32":
        try:  # own taskbar icon/grouping instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BalanceTracker.App")
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Balance Tracker")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    font = QFont("Segoe UI Variable Text" if sys.platform == "win32" else app.font().family())
    font.setPointSizeF(10)
    app.setFont(font)

    store = storage.Store()
    logs.setup(store.folder)
    log.info("Balance Tracker %s starting (data in %s)", __version__, store.folder)
    _install_error_handler(store)
    data = _load(store)
    theme.apply_theme(app, data.settings.theme)
    if applock.load(store.folder) is not None and not LockScreen(store.folder).exec():
        return 0
    win = MainWindow(store, data)
    win.show()
    QTimer.singleShot(250, win.startup_prompt)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
