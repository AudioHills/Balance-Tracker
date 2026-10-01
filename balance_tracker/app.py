"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from . import storage
from .models import AppData
from .ui import theme
from .ui.icon import app_icon
from .ui.main_window import MainWindow


def _load(store: storage.Store) -> AppData:
    try:
        return store.load()
    except Exception as e:  # corrupt or unreadable data file
        backups = [p for p in store.auto_backups() if p.name.startswith("auto-")]
        text = f"Your data file couldn't be opened:\n{e}"
        if backups:
            ans = QMessageBox.question(None, "Balance Tracker",
                                       text + f"\n\nRestore the most recent automatic backup ({backups[0].stem})?")
            if ans == QMessageBox.Yes:
                return storage.read_backup(backups[0])
        QMessageBox.critical(None, "Balance Tracker", text + f"\n\nThe file is at {store.path}.")
        sys.exit(1)


def main() -> int:
    if "--send-reminders" in sys.argv:  # run by Windows Task Scheduler; no window
        from . import notify
        try:
            notify.run_daily(storage.Store())
        except Exception as e:  # noqa: BLE001 - never crash a background task
            notify._log(storage.Store().folder, f"error: {e}")
            return 1
        return 0
    if sys.platform == "win32":
        try:  # own taskbar icon/grouping instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BalanceTracker.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Balance Tracker")
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    font = QFont("Segoe UI Variable Text" if sys.platform == "win32" else app.font().family())
    font.setPointSizeF(10)
    app.setFont(font)

    store = storage.Store()
    data = _load(store)
    theme.apply_theme(app, data.settings.theme)
    win = MainWindow(store, data)
    win.show()
    QTimer.singleShot(250, win.startup_prompt)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
