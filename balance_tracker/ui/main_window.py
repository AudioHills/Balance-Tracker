"""Main window: sidebar navigation, shared state, and all data-changing actions."""
from __future__ import annotations

import copy
from datetime import date, timedelta

from PySide6.QtCore import QObject, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import money, storage
from ..debts import full_forecast, make_plan
from ..forecast import Forecast, projection_end
from ..models import AppData, BILL, INCOME, Checkpoint, new_id
from . import theme
from .dialogs import (
    AffordDialog, CheckInDialog, DebtDialog, ItemDialog, NotifyDialog, RemindersDialog, WelcomeDialog,
)
from .icon import app_icon
from .pages import CheckinsPage, DashboardPage, DebtsPage, ItemsPage, LedgerPage, SettingsPage
from .widgets import hbox, label


class Toast(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10, 10)
        self.text = QLabel()
        self.text.setStyleSheet("font-weight: 600;")
        self.undo = QPushButton("Undo")
        self.undo.setObjectName("Chip")
        lay.addWidget(self.text)
        lay.addWidget(self.undo)
        self.fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.anim = QPropertyAnimation(self.fx, b"opacity", self)
        self.anim.finished.connect(self.hide)
        self.timer = QTimer(self, singleShot=True, timeout=self._fade)
        self._undo_cb = None
        self.undo.clicked.connect(self._do_undo)
        self.hide()

    def _do_undo(self):
        if self._undo_cb:
            self._undo_cb()
        self.hide()

    def show_text(self, text: str, undo_cb=None):
        self.text.setText(text)
        self._undo_cb = undo_cb
        self.undo.setVisible(undo_cb is not None)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2 + 110, par.height() - self.height() - 28)
        self.anim.stop()
        self.fx.setOpacity(1)
        self.show()
        self.raise_()
        self.timer.start(5000 if undo_cb else 2600)

    def _fade(self):
        self.anim.setDuration(400)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()


class _Sender(QObject):
    """Sends the daily digest off the UI thread."""
    done = Signal(str, list)  # (date sent, errors)


class MainWindow(QMainWindow):
    NAV = ["Dashboard", "Day by day", "Income & Bills", "Debts", "Check-ins", "Settings"]

    def __init__(self, store: storage.Store, data: AppData):
        super().__init__()
        self.store = store
        self.data = data
        self.today = date.today()
        self._ledger_end = None
        self._undo = None
        money.set_symbol(data.settings.currency_symbol)
        self.setWindowTitle("Balance Tracker")
        self.setWindowIcon(app_icon())
        self.resize(1320, 900)
        self.setMinimumSize(1020, 680)
        self.recompute()

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.pages = [DashboardPage(self), LedgerPage(self), ItemsPage(self), DebtsPage(self),
                      CheckinsPage(self), SettingsPage(self)]
        for p in self.pages:
            self.stack.addWidget(p.widget)
        self.toast_w = Toast(self)
        self.go(0)

        for i in range(len(self.NAV)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, lambda i=i: self.go(i))
        QShortcut(QKeySequence("Ctrl+K"), self, self.check_in)
        QShortcut(QKeySequence("Ctrl+I"), self, lambda: self.add_item(INCOME))
        QShortcut(QKeySequence("Ctrl+B"), self, lambda: self.add_item(BILL))
        QShortcut(QKeySequence("Ctrl+D"), self, self.add_debt)
        QShortcut(QKeySequence("Ctrl+A"), self, self.afford)
        QShortcut(QKeySequence("Ctrl+T"), self, self.toggle_theme)

        # Roll the "today" marker over at midnight if the app is left open.
        self._sender = _Sender()
        self._sender.done.connect(self._digest_done)
        self.clock = QTimer(self, interval=60_000, timeout=self._tick)
        self.clock.start()
        self.refresh_all()

    # ---- layout --------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(230)
        v = QVBoxLayout(side)
        v.setContentsMargins(16, 22, 16, 18)
        v.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(34, 34))
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("Balance", "Brand"))
        names.addWidget(label("Tracker", "BrandSub"))
        brand.addWidget(logo)
        brand.addLayout(names, 1)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("ThemeToggle")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setFixedSize(36, 36)
        self.theme_btn.clicked.connect(self.toggle_theme)
        brand.addWidget(self.theme_btn, 0, Qt.AlignVCenter)
        v.addLayout(brand)
        v.addSpacing(22)
        self.nav_btns = []
        glyphs = ["◉", "☰", "⇅", "◈", "✓", "⚙"]
        for i, (name, g) in enumerate(zip(self.NAV, glyphs)):
            b = QPushButton(f"{g}   {name}".replace("&", "&&"))
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Ctrl+{i + 1}")
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            v.addWidget(b)
            self.nav_btns.append(b)
        v.addStretch(1)

        box = QFrame()
        box.setObjectName("Card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(2)
        self.side_label = label("", "SidebarBalanceLabel")
        from .widgets import EyeButton
        self.side_eye = EyeButton()
        self.side_eye.clicked.connect(self.toggle_balance)
        self.side_balance = label("—", "SidebarBalance")
        self.side_next = label("", "Hint", wrap=True)
        bl.addLayout(hbox(self.side_label, None, self.side_eye, spacing=4))
        bl.addWidget(self.side_balance)
        bl.addWidget(self.side_next)
        v.addWidget(box)
        v.addSpacing(10)
        ci = QPushButton("Check in balance")
        ci.setObjectName("Primary")
        ci.setToolTip("Ctrl+K")
        ci.clicked.connect(self.check_in)
        v.addWidget(ci)
        return side

    def toggle_balance(self):
        self.data.settings.hide_balance = not self.data.settings.hide_balance
        self.commit()

    def toggle_theme(self):
        self.data.settings.theme = "light" if theme.is_dark() else "dark"
        self.commit(theme_changed=True)

    def _update_theme_button(self):
        dark = theme.is_dark()
        self.theme_btn.setText("☀" if dark else "☾")
        self.theme_btn.setToolTip(("Switch to light mode" if dark else "Switch to dark mode") + "  (Ctrl+T)")

    def go(self, i: int):
        self.stack.setCurrentIndex(i)
        for k, b in enumerate(self.nav_btns):
            b.setChecked(k == i)

    def show_day(self, d: date):
        self.go(1)
        self.pages[1].show_day(d)

    # ---- state ---------------------------------------------------------
    def recompute(self):
        self.plan = make_plan(self.data, self.today) if self.data.debts and self.data.has_start else None
        self.forecast = self.build_forecast()

    def build_forecast(self, extra=None, data: AppData | None = None, end: date | None = None,
                       debt_extras: bool = True) -> Forecast:
        """The day-by-day forecast, including planned debt payments when that option is on."""
        if end is None:
            end = projection_end(self.data, self.today)
            if self._ledger_end and self._ledger_end > end:
                end = self._ledger_end
        return full_forecast(self.data, self.plan, self.today, end, extra, debt_extras, source=data)

    def extend_forecast(self, end: date):
        self._ledger_end = end
        self.recompute()

    def refresh_all(self):
        self._update_theme_button()
        for p in self.pages:
            p.refresh()
        f, s = self.forecast, self.data.settings
        self.side_label.setText(f"{s.account_name.upper()} · TODAY")
        bal = f.balance_on(self.today)
        from .widgets import MASK
        self.side_eye.set_state(s.hide_balance)
        self.side_balance.setText(MASK if s.hide_balance else money.fmt(bal))
        col = theme.colors()
        tone = "text" if s.hide_balance or bal is None or bal >= s.low_balance_threshold else \
            ("warning" if bal >= 0 else "negative")
        self.side_balance.setStyleSheet(f"color: {col[tone]};")
        nxt = f.next_income(self.today) if not f.empty else None
        self.side_next.setText(f"Next income {nxt.date.strftime('%b %d')} · {money.fmt(nxt.amount)}" if nxt else "")

    def commit(self, theme_changed: bool = False, toast: str | None = None, undoable: bool = False,
               restamp: bool = True):
        money.set_symbol(self.data.settings.currency_symbol)
        try:
            self.store.save(self.data, restamp=restamp)
        except OSError as e:
            QMessageBox.critical(self, "Couldn't save", f"Your changes could not be saved:\n{e}")
        self._write_sync()
        if theme_changed:
            theme.apply_theme(QApplication.instance(), self.data.settings.theme)
        self.recompute()
        self.refresh_all()
        if toast:
            self.toast(toast, undoable)

    def toast(self, text: str, undoable: bool = False):
        self.toast_w.show_text(text, self.undo if undoable and self._undo else None)

    def snapshot(self):
        self._undo = copy.deepcopy(self.data.to_dict())

    def undo(self):
        if self._undo:
            self.data = AppData.from_dict(self._undo)
            self._undo = None
            self.commit(toast="Undone")

    def _tick(self):
        self.maybe_send_digest()
        self.sync_in()
        if date.today() != self.today:
            self.today = date.today()
            self.recompute()
            self.refresh_all()

    # ---- actions -------------------------------------------------------
    def first_run(self) -> bool:
        dlg = WelcomeDialog(self)
        if dlg.exec():
            self.data.add_checkpoint(dlg.result_checkpoint)
            self.data.settings.account_name = dlg.result_account
            self.commit(toast="You're set! Now add your paycheque and bills.")
            self.go(2)
            return True
        return False

    def check_in(self):
        if not self.data.has_start:
            self.first_run()
            return
        dlg = CheckInDialog(self.data, self.today, self, builder=self.build_forecast)
        if dlg.exec():
            cp = dlg.result_checkpoint
            if cp.date == self.data.start.date:
                self.set_start(cp.date, cp.balance)
                return
            self.snapshot()
            self.data.add_checkpoint(cp)
            self.commit(toast="Check-in saved — forecast updated", undoable=True)

    def add_item(self, kind: str):
        dlg = ItemDialog(self.data, kind=kind, parent=self)
        if dlg.exec():
            self.data.items.append(dlg.result_item)
            self.commit(toast=f"Added “{dlg.result_item.name}”")

    def edit_item(self, item_id: str):
        item = self.data.item(item_id)
        if not item:
            return
        dlg = ItemDialog(self.data, item=item, parent=self)
        if dlg.exec():
            self.snapshot()
            self.data.items[self.data.items.index(item)] = dlg.result_item
            self.commit(toast="Saved", undoable=True)

    def duplicate_item(self, item_id: str):
        item = self.data.item(item_id)
        clone = copy.deepcopy(item)
        clone.id = new_id()
        clone.name = f"{item.name} (copy)"
        self.data.items.append(clone)
        self.commit()
        self.edit_item(clone.id)

    def toggle_item(self, item_id: str):
        item = self.data.item(item_id)
        item.active = not item.active
        self.commit(toast=f"“{item.name}” {'resumed' if item.active else 'paused'}")

    def delete_item(self, item_id: str):
        item = self.data.item(item_id)
        self.snapshot()
        self.data.items.remove(item)
        self.commit(toast=f"Deleted “{item.name}”", undoable=True)

    def set_override(self, item, key: str, cents):
        self.snapshot()
        item.overrides[key] = cents
        self.commit(toast="Skipped this occurrence" if cents is None else "Amount changed for this date",
                    undoable=True)

    def clear_override(self, item, key: str):
        item.overrides.pop(key, None)
        self.commit(toast="Restored")

    def afford(self):
        if not self.data.has_start:
            self.first_run()
            return
        dlg = AffordDialog(self.data, self.build_forecast, self.today, self)
        if dlg.exec():
            self.data.items.append(dlg.result_item)
            self.commit(toast=f"Added “{dlg.result_item.name}” as a one-time bill")

    def reminders(self):
        """Menu: email/phone reminders or calendar export."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("✉  Email && phone reminders…", self.notify_settings)
        m.addAction("📅  Export to my calendar…", self.calendar_export)
        m.exec(QCursor.pos())

    def notify_settings(self):
        from .. import notify
        dlg = NotifyDialog(self.data, self.store.folder, self)
        if not dlg.exec():
            return
        s = self.data.settings
        msg = "Reminder settings saved"
        try:
            if dlg.want_task:
                notify.install_task(s.notify_time)
                s.notify_task = True
                msg = f"Reminders on — you'll get them daily around {_ampm(s.notify_time)}"
            elif s.notify_task:
                notify.remove_task()
                s.notify_task = False
        except OSError as e:
            s.notify_task = False
            QMessageBox.warning(self, "Background reminders",
                                f"Reminders will be sent while Balance Tracker is open, but the background "
                                f"task couldn't be set up:\n{e}")
        self.commit(toast=msg)
        self.maybe_send_digest()

    def maybe_send_digest(self):
        """Send today's digest from the app if it's due (the scheduled task may not have run yet)."""
        import copy
        import threading
        from .. import notify
        if getattr(self, "_sending", False) or getattr(self, "_failed_day", None) == self.today \
                or not notify.due_now(self.data):
            return
        self._sending = True
        snapshot = copy.deepcopy(self.data)
        today = self.today
        folder = self.store.folder

        def work():
            digest = notify.compose(snapshot, today)
            errors = notify.deliver(snapshot, folder, digest) if digest else []
            notify._log(folder, "app: " + ("; ".join(errors) or ("sent" if digest else "nothing to send")))
            self._sender.done.emit(today.isoformat(), errors)
        threading.Thread(target=work, daemon=True).start()

    def _digest_done(self, day: str, errors: list):
        self._sending = False
        if errors:
            self._failed_day = date.fromisoformat(day)  # don't retry every minute
            self.toast("Couldn't send today's reminder — check Email & phone reminders")
            return
        self.data.settings.notify_last_sent = day
        self.commit()

    def calendar_export(self):
        dlg = RemindersDialog(self.data, self.plan, self.today, self)
        if dlg.exec():
            self.commit(toast=f"Saved {dlg.saved_count} reminders — now import the file into your phone's calendar")

    def mark_card_paid(self, key: str):
        self.snapshot()
        self.data.card_paid.append(key)
        self.commit(toast="Marked as paid", undoable=True)

    def add_debt(self):
        dlg = DebtDialog(self.data, parent=self)
        if dlg.exec():
            self.data.debts.append(dlg.result_debt)
            self.commit(toast=f"Added “{dlg.result_debt.name}”")

    def edit_debt(self, debt_id: str):
        debt = self.data.debt(debt_id)
        if not debt:
            return
        dlg = DebtDialog(self.data, debt, parent=self)
        if dlg.exec():
            self.snapshot()
            self.data.debts[self.data.debts.index(debt)] = dlg.result_debt
            self.commit(toast="Debt updated — plan recalculated", undoable=True)

    def delete_debt(self, debt_id: str):
        debt = self.data.debt(debt_id)
        self.snapshot()
        self.data.debts.remove(debt)
        for item in self.data.items:
            if item.paid_with == debt_id:
                item.paid_with = ""
        self.commit(toast=f"Deleted “{debt.name}”", undoable=True)

    def delete_checkpoint(self, cp_id: str):
        cp = next((c for c in self.data.checkpoints if c.id == cp_id), None)
        if not cp or cp is self.data.start:
            return
        self.snapshot()
        self.data.checkpoints.remove(cp)
        self.commit(toast="Check-in deleted", undoable=True)

    def set_start(self, d: date, cents: int):
        self.snapshot()
        old = self.data.start
        if old:
            self.data.checkpoints.remove(old)
        self.data.checkpoints.append(Checkpoint(d, cents, includes_today=old.includes_today if old else True,
                                                note="Starting balance"))
        self.commit(toast="Starting balance updated", undoable=True)

    # ---- backup / restore ----------------------------------------------
    def export_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export backup",
                                              f"BalanceTracker-backup-{self.today.isoformat()}.json",
                                              "Balance Tracker backup (*.json)")
        if path:
            storage.export_backup(self.data, path)
            self.toast("Backup exported")

    def import_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import backup", "", "Balance Tracker backup (*.json)")
        if path:
            self.restore_from(path, ask_merge=True)

    def restore_from(self, path: str, ask_merge: bool = False):
        try:
            incoming = storage.read_backup(path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            QMessageBox.warning(self, "Can't import", f"That file couldn't be read:\n{e}")
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Restore backup")
        msg.setText(f"This backup has {len(incoming.items)} income/bill entries and "
                    f"{len(incoming.checkpoints)} balance entries.")
        msg.setInformativeText("Replace everything with the backup? A safety copy of your current data "
                               "is saved first.")
        replace = msg.addButton("Replace", QMessageBox.AcceptRole)
        merge = msg.addButton("Merge (add missing)", QMessageBox.ActionRole) if ask_merge else None
        msg.addButton(QMessageBox.Cancel)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked not in (replace, merge) or clicked is None:
            return
        self.store.safety_backup(self.data)
        self.snapshot()
        if clicked is replace:
            self.data = incoming
        else:
            self.data = storage.merge_data(self.data, incoming)
        self.commit(theme_changed=True, toast="Backup restored", undoable=True)

    def reset_all(self):
        if QMessageBox.question(self, "Erase all data",
                                "Erase all incomes, bills and check-ins? A safety backup is saved first.") \
                != QMessageBox.Yes:
            return
        self.store.safety_backup(self.data)
        settings = self.data.settings
        self.data = AppData(settings=settings)
        self.commit(toast="All data erased (a safety backup was saved)")
        self.first_run()

    # ---- startup -------------------------------------------------------
    def startup_prompt(self):
        QTimer.singleShot(1500, self.maybe_send_digest)
        self.sync_in(force=True)
        if not self.data.has_start:
            self.first_run()
        elif self.data.settings.prompt_on_open and self.data.latest_checkpoint.date < self.today:
            self.check_in()

    # ---- iPhone sync ---------------------------------------------------
    def sync_folder(self):
        from pathlib import Path
        s = self.data.settings
        return Path(s.sync_folder) if s.sync_enabled and s.sync_folder else None

    def _write_sync(self):
        from .. import sync
        folder = self.sync_folder()
        if folder is None:
            return
        try:
            sync.write_sync_file(folder, self.data)
            self._sync_seen = self._sync_mtimes(folder)
            self._sync_error = ""
        except OSError as e:
            self._sync_error = str(e)

    @staticmethod
    def _sync_mtimes(folder) -> dict:
        from .. import sync
        out = {}
        for p in sync.sync_files(folder):
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                pass
        return out

    def sync_in(self, force: bool = False) -> int:
        """Merge changes the iPhone saved into the sync folder. Returns 1 if anything changed."""
        import shutil
        from datetime import datetime as _dt
        from .. import storage, sync
        folder = self.sync_folder()
        if folder is None:
            return 0
        mtimes = self._sync_mtimes(folder)
        if not force and mtimes == getattr(self, "_sync_seen", None):
            return 0
        merged = self.data
        extras = []
        for p in sync.sync_files(folder):
            try:
                merged = sync.merge(merged, storage.read_backup(p))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # half-downloaded or not ours; try again next time
            if p.name != sync.SYNC_FILE:
                extras.append(p)
        self._sync_seen = mtimes
        self._last_sync = _dt.now()
        changed = not sync.same(merged, self.data)
        if changed:
            self.data = merged
            self.commit(toast="📱 Synced changes from your iPhone", restamp=False)
        for p in extras:  # copies like "BalanceTracker-sync 2.json" are merged; tidy them away
            try:
                self.store.backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(self.store.backup_dir / f"merged-{_dt.now():%Y%m%d-%H%M%S}-{p.name}"))
            except OSError:
                pass
        if extras and not changed:
            self._write_sync()
        return int(changed)

    def enable_sync(self, folder: str | None):
        s = self.data.settings
        s.sync_enabled = bool(folder)
        if folder:
            s.sync_folder = folder
        self.commit()
        if folder:
            self.sync_in(force=True)
            self._write_sync()
            self.toast("iPhone sync is on — open the phone app and tap Sync")

    def changeEvent(self, e):
        from PySide6.QtCore import QEvent
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and self.isActiveWindow() and hasattr(self, "pages"):
            QTimer.singleShot(300, self.sync_in)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast_w.isVisible():
            self.toast_w.move((self.width() - self.toast_w.width()) // 2 + 110,
                              self.height() - self.toast_w.height() - 28)


def _ampm(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"
