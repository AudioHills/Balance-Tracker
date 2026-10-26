"""Main window: sidebar navigation, shared state, and every action that changes the data."""
from __future__ import annotations

import contextlib
import copy
import logging
import sys
import time
from datetime import date
from pathlib import Path

from PySide6.QtCore import QEvent, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import applock, money, notify, secure_store, storage, sync
from ..debts import Plan, full_forecast, make_plan
from ..encryption import FileKey
from ..forecast import Forecast, change_amount_from, projection_end
from ..formatting import ampm, month_day
from ..models import BILL, INCOME, AppData, Checkpoint, RecurringItem, new_id
from . import theme
from .dialogs import (
    AffordDialog,
    BackupPasswordDialog,
    ChangeAmountDialog,
    CheckInDialog,
    DebtDialog,
    ItemDialog,
    LockScreen,
    LockSetupDialog,
    NotifyDialog,
    RemindersDialog,
    ShortcutsDialog,
    SyncPassphraseDialog,
    WelcomeDialog,
    ask_password,
)
from .icon import app_icon
from .pages import CheckinsPage, DashboardPage, DebtsPage, ItemsPage, LedgerPage, Page, SettingsPage
from .widgets import MASK, EyeButton, hbox, label
from .workers import run_in_background

log = logging.getLogger(__name__)

SIDEBAR_WIDTH = 230
UNDO_LEVELS = 25
LEDGER, ITEMS, SETTINGS = 1, 2, 5  # page indexes used by actions
SYNC_KEY = "sync_key"  # name of the sync-file key in secrets.json


def system_idle_seconds() -> float | None:
    """Seconds since the last keyboard/mouse input anywhere on Windows, or None elsewhere."""
    if sys.platform != "win32":
        return None
    import ctypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


class Toast(QFrame):
    """A short message near the bottom of the window, optionally with an Undo button."""

    def __init__(self, parent: QMainWindow):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10, 10)
        self.text = QLabel()
        self.text.setTextFormat(Qt.PlainText)  # messages include names from the data
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
        self.hide()
        if self._undo_cb:
            self._undo_cb()

    def show_text(self, text: str, undo_cb=None):
        self.text.setText(text)
        self._undo_cb = undo_cb
        self.undo.setVisible(undo_cb is not None)
        self.adjustSize()
        self.place()
        self.anim.stop()
        self.fx.setOpacity(1)
        self.show()
        self.raise_()
        self.timer.start(5000 if undo_cb else 2600)

    def place(self):
        """Centred over the page area (right of the sidebar), near the bottom."""
        par = self.parentWidget()
        left = SIDEBAR_WIDTH + (par.width() - SIDEBAR_WIDTH - self.width()) // 2
        self.move(max(0, left), par.height() - self.height() - 28)

    def _fade(self):
        self.anim.setDuration(400)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()


class MainWindow(QMainWindow):
    NAV = [("◉", "Dashboard"), ("☰", "Day by day"), ("⇅", "Income & Bills"), ("◈", "Debts"), ("✓", "Check-ins"),
           ("⚙", "Settings")]

    def __init__(self, store: storage.Store, data: AppData, today: date | None = None):
        super().__init__()
        self.store = store
        self.data = data
        self.today = today or date.today()
        self.plan: Plan | None = None
        self.sync_error = ""  # last problem writing the iPhone sync file, shown in Settings
        self.sync_refused: list[str] = []  # sync-folder files that were refused (wrong passphrase…)
        self.sync_key = self._load_sync_key()
        self._locked = False
        self._last_input = time.monotonic()  # for the idle lock where Windows' own idle time isn't available
        self._watching_input = False
        self.lock_cfg = applock.load(store.folder)
        self._ledger_end: date | None = None
        self._undo_stack: list[dict] = []
        self._sending = False  # a reminder digest is being sent
        self._failed_day: date | None = None  # don't retry a failed digest every minute
        self._sync_seen: dict | None = None  # sync-folder file times at the last merge
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

        self.pages: list[Page] = [DashboardPage(self), LedgerPage(self), ItemsPage(self), DebtsPage(self),
                                  CheckinsPage(self), SettingsPage(self)]
        for p in self.pages:
            self.stack.addWidget(p.widget)
        self.toast_w = Toast(self)
        self._install_shortcuts()

        # Once a minute: send a due reminder, pick up iPhone edits, roll "today" over at midnight.
        self.clock = QTimer(self, interval=60_000, timeout=self._tick)
        self.clock.start()
        self.idle_timer = QTimer(self, interval=15_000, timeout=self._check_idle)
        self.idle_timer.start()
        self._update_idle_watch()
        for p in self.pages:  # every page starts complete; afterwards they refresh when shown
            p.refresh()
            p.dirty = False
        self.go(0)
        self.refresh_all()

    # ---- layout --------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(SIDEBAR_WIDTH)
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
        for i, (glyph, name) in enumerate(self.NAV):
            b = QPushButton(f"{glyph}   {name}".replace("&", "&&"))
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

    def _install_shortcuts(self):
        """One table drives both the key bindings and the F1 list."""
        self.shortcuts = [
            ("Ctrl+K", "Check in your balance", self.check_in),
            ("Ctrl+I", "Add income", lambda: self.add_item(INCOME)),
            ("Ctrl+B", "Add a bill", lambda: self.add_item(BILL)),
            ("Ctrl+D", "Add a debt", self.add_debt),
            ("Ctrl+A", "Can I afford it?", self.afford),
            ("Ctrl+F", "Search Day by day or Income & Bills", self.focus_search),
            ("Ctrl+Z", "Undo the last change", self.undo),
            ("Ctrl+T", "Switch between light and dark", self.toggle_theme),
            ("Ctrl+L", "Lock Balance Tracker (once a password is set)", self.lock_now),
            ("F1", "Show these shortcuts", self.show_shortcuts),
        ]
        for i in range(len(self.NAV)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, lambda i=i: self.go(i))
        for keys, _, action in self.shortcuts:
            QShortcut(QKeySequence(keys), self, action)

    def show_shortcuts(self):
        rows = [(f"Ctrl+1 … Ctrl+{len(self.NAV)}", "Go to " + ", ".join(n for _, n in self.NAV))]
        ShortcutsDialog(rows + [(k, what) for k, what, _ in self.shortcuts], self).exec()

    def focus_search(self):
        if not self.pages[self.stack.currentIndex()].focus_search():
            self.go(LEDGER)
            self.pages[LEDGER].focus_search()

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
        if self.pages[i].dirty:
            self._refresh_page(i)

    def show_day(self, d: date):
        self.go(LEDGER)
        self.pages[LEDGER].show_day(d)

    # ---- state ---------------------------------------------------------
    def recompute(self):
        self.plan = make_plan(self.data, self.today) if self.data.debts and self.data.has_start else None
        self.forecast = self.build_forecast()

    def build_forecast(self, extra=None, data: AppData | None = None, end: date | None = None,
                       debt_extras: bool = True) -> Forecast:
        """The day-by-day forecast, including planned debt payments when that option is on.
        `data` projects a modified copy (e.g. without today's check-in)."""
        if end is None:
            end = projection_end(self.data, self.today)
            if self._ledger_end and self._ledger_end > end:
                end = self._ledger_end
        return full_forecast(self.data, self.plan, self.today, end, extra, debt_extras, source=data)

    def extend_forecast(self, end: date):
        """Make the forecast reach `end` (the Day by day page can look further ahead than usual)."""
        self._ledger_end = end
        self.recompute()

    def refresh_all(self):
        """Bring the sidebar and the visible page up to date; other pages catch up when shown."""
        self._update_theme_button()
        self._refresh_sidebar()
        for p in self.pages:
            p.dirty = True
        self._refresh_page(self.stack.currentIndex())

    def _refresh_page(self, i: int):
        self.pages[i].refresh()
        self.pages[i].dirty = False

    def _refresh_sidebar(self):
        f, s = self.forecast, self.data.settings
        self.side_label.setText(f"{s.account_name.upper()} · TODAY")
        bal = f.balance_on(self.today)
        self.side_eye.set_state(s.hide_balance)
        self.side_balance.setText(MASK if s.hide_balance else money.fmt(bal))
        if s.hide_balance or bal is None or bal >= s.low_balance_threshold:
            tone = "text"
        else:
            tone = "warning" if bal >= 0 else "negative"
        self.side_balance.setStyleSheet(f"color: {theme.colors()[tone]};")
        nxt = f.next_income(self.today) if not f.empty else None
        self.side_next.setText(f"Next income {month_day(nxt.date)} · {money.fmt(nxt.amount)}" if nxt else "")

    def commit(self, theme_changed: bool = False, toast: str | None = None, undoable: bool = False,
               restamp: bool = True):
        """Save the data, push it to the sync folder, recompute and refresh."""
        money.set_symbol(self.data.settings.currency_symbol)
        try:
            self.store.save(self.data, restamp=restamp)
        except OSError as e:
            log.error("Saving failed: %s", e)
            QMessageBox.critical(self, "Couldn't save", f"Your changes could not be saved:\n{e}")
        self._write_sync()
        if theme_changed:
            theme.apply_theme(QApplication.instance(), self.data.settings.theme)
        self.recompute()
        self.refresh_all()
        if toast:
            self.toast(toast, undoable)

    def toast(self, text: str, undoable: bool = False):
        self.toast_w.show_text(text, self.undo if undoable and self._undo_stack else None)

    def snapshot(self):
        """Remember the data as it is now, so the next change can be undone."""
        self._undo_stack.append(self.data.to_dict())
        del self._undo_stack[:-UNDO_LEVELS]

    def undo(self):
        if not self._undo_stack:
            self.toast("Nothing to undo")
            return
        old_theme = self.data.settings.theme
        self.data = self._keep_security(AppData.from_dict(self._undo_stack.pop()))
        self.commit(theme_changed=self.data.settings.theme != old_theme, toast="Undone")

    def _keep_security(self, new: AppData) -> AppData:
        """Undo and restoring a backup bring back old data, but never switch sync encryption off (or on):
        that only changes through Settings."""
        new.settings.sync_encrypt = self.data.settings.sync_encrypt
        return new

    def _tick(self):
        self.maybe_send_digest()
        self.sync_in()
        if date.today() != self.today:
            self.today = date.today()
            self.recompute()
            self.refresh_all()

    # ---- actions -------------------------------------------------------
    def first_run(self) -> bool:
        dlg = WelcomeDialog(self, today=self.today)
        if dlg.exec():
            self.data.add_checkpoint(dlg.result_checkpoint)
            self.data.settings.account_name = dlg.result_account
            self.commit(toast="You're set! Now add your paycheque and bills.")
            self.go(ITEMS)
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
        dlg = ItemDialog(self.data, kind=kind, parent=self, today=self.today)
        if dlg.exec():
            self.snapshot()
            self.data.items.append(dlg.result_item)
            self.commit(toast=f"Added “{dlg.result_item.name}”", undoable=True)

    def edit_item(self, item_id: str):
        item = self.data.item(item_id)
        if not item:
            return
        dlg = ItemDialog(self.data, item=item, parent=self, today=self.today)
        if dlg.exec():
            self.snapshot()
            self.data.items[self.data.items.index(item)] = dlg.result_item
            self.commit(toast="Saved", undoable=True)

    def duplicate_item(self, item_id: str):
        """Open a copy in the editor; nothing is added unless it's saved."""
        item = self.data.item(item_id)
        if not item:
            return
        clone = copy.deepcopy(item)
        clone.id = new_id()
        clone.updated = ""
        clone.name = f"{item.name} (copy)"
        dlg = ItemDialog(self.data, item=clone, parent=self, today=self.today, title="Duplicate entry",
                         ok_text="Add copy")
        if dlg.exec():
            self.snapshot()
            self.data.items.append(dlg.result_item)
            self.commit(toast=f"Added “{dlg.result_item.name}”", undoable=True)

    def change_amount_from(self, item_id: str, when: date | None = None):
        """New amount from a date on (rent going up), keeping earlier dates as they were."""
        item = self.data.item(item_id)
        if not item:
            return
        dlg = ChangeAmountDialog(item, self.today, when, self)
        if not dlg.exec():
            return
        head, tail = change_amount_from(item, dlg.result_when, dlg.result_amount)
        if head.to_dict() == item.to_dict() and tail is None:
            self.toast("Nothing is scheduled on or after that date")
            return
        self.snapshot()
        self.data.items[self.data.items.index(item)] = head
        if tail is not None:
            self.data.items.append(tail)
        self.commit(toast=f"“{item.name}” is {money.fmt(dlg.result_amount)} from {month_day(dlg.result_when)} on",
                    undoable=True)

    def toggle_item(self, item_id: str):
        item = self.data.item(item_id)
        self.snapshot()
        item.active = not item.active
        self.commit(toast=f"“{item.name}” {'resumed' if item.active else 'paused'}", undoable=True)

    def delete_item(self, item_id: str):
        item = self.data.item(item_id)
        self.snapshot()
        self.data.items.remove(item)
        self.commit(toast=f"Deleted “{item.name}”", undoable=True)

    def set_override(self, item: RecurringItem, key: str, cents: int | None):
        """Skip one occurrence (cents=None) or change its amount, without touching the schedule."""
        self.snapshot()
        item.overrides[key] = cents
        self.commit(toast="Skipped this occurrence" if cents is None else "Amount changed for this date",
                    undoable=True)

    def clear_override(self, item: RecurringItem, key: str):
        self.snapshot()
        item.overrides.pop(key, None)
        self.commit(toast="Restored the normal amount", undoable=True)

    def afford(self):
        if not self.data.has_start:
            self.first_run()
            return
        dlg = AffordDialog(self.data, self.build_forecast, self.today, self)
        if dlg.exec():
            self.snapshot()
            self.data.items.append(dlg.result_item)
            self.commit(toast=f"Added “{dlg.result_item.name}” as a one-time bill", undoable=True)

    def reminders(self):
        """Menu: email/phone reminders or calendar export."""
        m = QMenu(self)
        m.addAction("✉  Email && phone reminders…", self.notify_settings)
        m.addAction("📅  Export to my calendar…", self.calendar_export)
        m.exec(QCursor.pos())

    def notify_settings(self):
        dlg = NotifyDialog(self.data, self.store.folder, self)
        if not dlg.exec():
            return
        s = self.data.settings
        msg = "Reminder settings saved"
        try:
            if dlg.want_task:
                notify.install_task(s.notify_time)
                s.notify_task = True
                msg = f"Reminders on — you'll get them daily around {ampm(s.notify_time)}"
            elif s.notify_task:
                notify.remove_task()
                s.notify_task = False
        except OSError as e:
            log.warning("Couldn't set up the reminder task: %s", e)
            s.notify_task = False
            QMessageBox.warning(self, "Background reminders",
                                "Reminders will be sent while Balance Tracker is open, but the background "
                                f"task couldn't be set up:\n{e}")
        self.commit(toast=msg)
        self.maybe_send_digest()

    def maybe_send_digest(self):
        """Send today's digest from the app if it's due (the scheduled task may not have run yet)."""
        if self._sending or self._failed_day == self.today or not notify.due_now(self.data):
            return
        self._sending = True
        snapshot, today, folder = copy.deepcopy(self.data), self.today, self.store.folder

        def work() -> list:
            digest = notify.compose(snapshot, today)
            errors = notify.deliver(snapshot, folder, digest) if digest else []
            notify.log_activity(folder, "app: " + ("; ".join(errors) or ("sent" if digest else "nothing to send")))
            return errors

        run_in_background(self, work, lambda errors, crash: self._digest_done(today, [str(crash)] if crash else errors))

    def _digest_done(self, day: date, errors: list):
        self._sending = False
        if errors:
            self._failed_day = day
            self.toast("Couldn't send today's reminder — check Email & phone reminders")
            return
        self.data.settings.notify_last_sent = day.isoformat()
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
        dlg = DebtDialog(self.data, parent=self, today=self.today)
        if dlg.exec():
            self.snapshot()
            self.data.debts.append(dlg.result_debt)
            self.commit(toast=f"Added “{dlg.result_debt.name}”", undoable=True)

    def edit_debt(self, debt_id: str):
        debt = self.data.debt(debt_id)
        if not debt:
            return
        dlg = DebtDialog(self.data, debt, parent=self, today=self.today)
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
        cp = self.data.checkpoint(cp_id)
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
        dlg = BackupPasswordDialog(self)
        if not dlg.exec():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export backup",
                                              f"BalanceTracker-backup-{self.today.isoformat()}.json",
                                              "Balance Tracker backup (*.json)")
        if path:
            try:
                storage.export_backup(self.data, path, dlg.result_password)
            except OSError as e:
                QMessageBox.warning(self, "Couldn't export", f"The backup couldn't be saved:\n{e}")
                return
            self.toast("Backup exported 🔒 — keep the password safe" if dlg.result_password else "Backup exported")

    def import_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import backup", "", "Balance Tracker backup (*.json)")
        if path:
            self.restore_from(path, ask_merge=True)

    def restore_from(self, path: str, ask_merge: bool = False):
        def ask(problem: str) -> str | None:
            return ask_password(self, "Password-protected backup", "Enter the password for this backup:", problem)

        try:
            incoming = storage.read_backup(path, ask, keys=[self.sync_key])
        except storage.ImportCancelled:
            return
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
        if clicked is None or clicked not in (replace, merge):
            return
        self.store.safety_backup(self.data)
        self.snapshot()
        self.data = self._keep_security(incoming) if clicked is replace else storage.merge_data(self.data, incoming)
        self.commit(theme_changed=True, toast="Backup restored", undoable=True)

    def reset_all(self):
        if QMessageBox.question(self, "Erase all data",
                                "Erase all incomes, bills and check-ins? A safety backup is saved first.") \
                != QMessageBox.Yes:
            return
        self.store.safety_backup(self.data)
        self.snapshot()
        self.data = AppData(settings=self.data.settings)
        self.commit(toast="All data erased (a safety backup was saved)", undoable=True)
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
    def sync_folder(self) -> Path | None:
        s = self.data.settings
        return Path(s.sync_folder) if s.sync_enabled and s.sync_folder else None

    def _load_sync_key(self) -> FileKey | None:
        raw = secure_store.get_json(self.store.folder, SYNC_KEY)
        try:
            return FileKey.from_dict(raw) if raw else None
        except (KeyError, TypeError, ValueError):
            return None

    def _write_sync(self):
        folder = self.sync_folder()
        if folder is None:
            return
        encrypt = self.data.settings.sync_encrypt
        if encrypt and self.sync_key is None:  # never fall back to writing it unencrypted
            self.sync_error = ("The sync passphrase isn't stored on this PC any more. Set it again with "
                               "“Change passphrase…” below.")
            return
        try:
            sync.write_sync_file(folder, self.data, self.sync_key if encrypt else None)
            self._sync_seen = self._sync_mtimes(folder)
            self.sync_error = ""
        except OSError as e:
            log.warning("Couldn't write the sync file: %s", e)
            self.sync_error = str(e)

    @staticmethod
    def _sync_mtimes(folder: Path) -> dict[str, float]:
        out = {}
        for p in sync.sync_files(folder):
            with contextlib.suppress(OSError):  # vanished between listing and stat; the next tick sees it
                out[str(p)] = p.stat().st_mtime
        return out

    def sync_in(self, force: bool = False) -> int:
        """Merge changes the iPhone saved into the sync folder. Returns 1 if anything changed."""
        folder = self.sync_folder()
        if folder is None:
            return 0
        mtimes = self._sync_mtimes(folder)
        if not force and mtimes == self._sync_seen:
            return 0
        encrypt = self.data.settings.sync_encrypt
        result = sync.pull_folder(folder, self.data, self.sync_key if encrypt else None, require_encrypted=encrypt)
        self._sync_seen = mtimes
        self._sync_refused(result.problems)
        if result.changed:
            self.data = result.data
            # Undoing to before the merge would delete whatever the phone added, on both devices.
            self._undo_stack.clear()
            self.commit(toast="📱 Synced changes from your iPhone", restamp=False)
        for p in result.copies:  # copies like "BalanceTracker-sync 2.json" are merged; tidy them away
            self.store.archive_sync_copy(p)
        if result.copies and not result.changed:
            self._write_sync()
        return int(result.changed)

    def _sync_refused(self, problems: list[str]):
        """Report files in the sync folder that weren't merged (once each, then in Settings)."""
        new = [p for p in problems if p not in self.sync_refused]
        self.sync_refused = problems
        if new:
            self.toast("📱 " + new[0])
        if new or not problems:
            self.pages[SETTINGS].dirty = True
            if self.stack.currentIndex() == SETTINGS:
                self._refresh_page(SETTINGS)

    def set_sync_passphrase(self):
        dlg = SyncPassphraseDialog(self)
        if not dlg.exec():
            return
        passphrase = dlg.result_passphrase
        QApplication.setOverrideCursor(Qt.WaitCursor)
        run_in_background(self, lambda: FileKey.derive(passphrase), self._sync_key_ready)

    def _sync_key_ready(self, key: FileKey | None, error: Exception | None):
        QApplication.restoreOverrideCursor()
        try:
            if error is not None:
                raise OSError(str(error))
            secure_store.put_json(self.store.folder, SYNC_KEY, key.to_dict())
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save the passphrase", str(e))
            return
        self.sync_key = key
        self.data.settings.sync_encrypt = True
        self.sync_refused = []
        self.commit(toast="🔒 Sync file encrypted — on your iPhone, choose the sync file again and enter "
                          "the passphrase")

    def turn_off_sync_encryption(self):
        if QMessageBox.question(self, "Stop encrypting the sync file?",
                                "Your finances will be stored in iCloud Drive without a passphrase, readable by "
                                "anyone who can open that folder. Continue?") != QMessageBox.Yes:
            return
        try:
            secure_store.put_json(self.store.folder, SYNC_KEY, None)
        except OSError as e:
            QMessageBox.warning(self, "Couldn't remove the passphrase", str(e))
            return
        self.sync_key = None
        self.data.settings.sync_encrypt = False
        self.sync_refused = []
        self.commit(toast="The sync file is no longer encrypted")

    # ---- app lock ------------------------------------------------------
    def lock_settings(self):
        cfg = applock.load(self.store.folder)
        if LockSetupDialog(self.store.folder, cfg, self).exec():
            self._lock_changed()
            self.toast("🔒 Lock updated" if cfg else "🔒 Balance Tracker will ask for your password when it opens")

    def _lock_changed(self):
        self.lock_cfg = applock.load(self.store.folder)
        self._update_idle_watch()
        self.refresh_all()

    def _update_idle_watch(self):
        """Where Windows can't say how long the user has been away, watch this app's own input
        events, but only while an idle lock is set (an app-wide event filter isn't free)."""
        cfg = self.lock_cfg
        want = bool(cfg and cfg.idle_minutes) and system_idle_seconds() is None
        if want != self._watching_input:
            app = QApplication.instance()
            if want:
                app.installEventFilter(self)
            else:
                app.removeEventFilter(self)
            self._watching_input = want

    def remove_lock(self):
        if applock.load(self.store.folder) is None:
            return
        pw = ask_password(self, "Turn off the lock", "Enter your password to turn off the lock:")
        while pw is not None:
            if applock.check(self.store.folder, pw):
                applock.remove(self.store.folder)
                self._lock_changed()
                self.toast("Lock turned off")
                return
            wait = applock.load(self.store.folder).wait_seconds()
            problem = f"Too many wrong passwords — wait {wait} s." if wait else "That password isn't right."
            pw = ask_password(self, "Turn off the lock", "Enter your password to turn off the lock:", problem)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.Wheel):
            self._last_input = time.monotonic()
        return False

    def _check_idle(self):
        cfg = self.lock_cfg
        if self._locked or cfg is None or not cfg.idle_minutes:
            return
        idle = system_idle_seconds()
        if idle is None:
            idle = time.monotonic() - self._last_input
        if idle >= cfg.idle_minutes * 60:
            self.lock_now(auto=True)

    def lock_now(self, auto: bool = False, minimized: bool = False):
        """Hide everything behind the lock screen. Open dialogs are closed (as if cancelled)."""
        if self._locked:
            return
        self.lock_cfg = applock.load(self.store.folder)
        if self.lock_cfg is None:
            if not auto:
                self.toast("Set a lock password first: Settings → Security")
            return
        self._locked = True
        try:
            for w in QApplication.topLevelWidgets():
                if w is not self and w.isVisible():
                    w.hide()
            self.toast_w.hide()
            maximized = self.isMaximized()
            self.hide()
            screen = LockScreen(self.store.folder)
            if minimized:
                screen.setWindowState(Qt.WindowMinimized)
            if not screen.exec():
                QApplication.quit()
                return
            self.showMaximized() if maximized else self.showNormal()
            self.raise_()
            self.activateWindow()
        finally:
            self._locked = False
            self._last_input = time.monotonic()

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
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and self.isActiveWindow() and hasattr(self, "pages"):
            QTimer.singleShot(300, self.sync_in)
        if e.type() == QEvent.WindowStateChange and self.isMinimized() and hasattr(self, "pages") \
                and not self._locked:
            cfg = self.lock_cfg
            if cfg and cfg.lock_on_minimize:
                QTimer.singleShot(0, lambda: self.lock_now(auto=True, minimized=True))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast_w.isVisible():
            self.toast_w.place()
