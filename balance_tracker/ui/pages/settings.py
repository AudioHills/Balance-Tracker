"""Settings: preferences, the starting balance, iPhone sync, backups and updates."""
from __future__ import annotations

import os
import sys
from html import escape

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from ... import WEB_APP_URL, __version__, logs, money, sync, updates
from .. import theme
from ..widgets import Card, MoneySpin, date_edit, hbox, label, repolish
from ..workers import run_in_background
from .common import Page

THEMES = (("system", "Match Windows"), ("light", "Light"), ("dark", "Dark"))


class SettingsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Settings", "Preferences, starting balance, and your data.")
        self._loading = True
        self._build_preferences()
        self._build_start()
        self._build_sync()
        self._build_data()
        self._build_about()
        self.body.addStretch(1)
        self._loading = False

    # ---- layout ----------------------------------------------------------
    def _build_preferences(self):
        pref = Card()
        pref.lay.addWidget(label("Preferences", "SectionTitle"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        self.account = QLineEdit()
        self.theme = QComboBox()
        for key, text in THEMES:
            self.theme.addItem(text, key)
        self.currency = QLineEdit()
        self.currency.setMaxLength(4)
        self.currency.setMaximumWidth(80)
        self.cushion = MoneySpin()
        self.horizon = QSpinBox()
        self.horizon.setRange(1, 36)
        self.horizon.setSuffix(" months")
        self.prompt = QCheckBox("Ask for my current balance when the app opens")
        form.addRow("Account name", self.account)
        form.addRow("Theme", self.theme)
        form.addRow("Currency symbol", self.currency)
        form.addRow("Low-balance cushion", hbox(self.cushion, label(
            "You'll be warned when the forecast dips below this.", "Hint"), None))
        form.addRow("Watch ahead", hbox(self.horizon, label(
            "How far ahead alerts and “lowest point” look.", "Hint"), None))
        form.addRow("", self.prompt)
        pref.lay.addLayout(form)
        self.body.addWidget(pref)

        self.account.editingFinished.connect(
            lambda: self._set("account_name", self.account.text().strip() or "Chequing"))
        self.currency.editingFinished.connect(
            lambda: self._set("currency_symbol", self.currency.text().strip() or "$"))
        self.cushion.editingFinished.connect(lambda: self._set("low_balance_threshold", self.cushion.cents()))
        self.horizon.valueChanged.connect(lambda v: self._set("forecast_months", v))
        self.theme.currentIndexChanged.connect(lambda _: self._set("theme", self.theme.currentData()))
        self.prompt.toggled.connect(lambda on: self._set("prompt_on_open", on))

    def _build_start(self):
        start = Card()
        start.lay.addWidget(label("Starting balance", "SectionTitle"))
        start.lay.addWidget(label("Where the day-by-day history begins. Later check-ins build on this.",
                                  "Hint", wrap=True))
        self.start_bal = MoneySpin(allow_negative=True)
        self.start_date = date_edit(self.ctx.today)
        save_start = QPushButton("Update starting balance")
        save_start.clicked.connect(self.save_start)
        start.lay.addLayout(hbox(self.start_bal, label("as of", "Muted"), self.start_date, save_start, None))
        self.body.addWidget(start)

    def _build_sync(self):
        phone = Card()
        phone.lay.addWidget(label("📱 iPhone sync (through iCloud Drive)", "SectionTitle"))
        phone.lay.addWidget(label(
            "Use Balance Tracker on your iPhone too. This PC keeps a sync file in your iCloud Drive; the phone "
            "app reads it and saves its changes back. Edits on either device are merged — the newest wins.",
            "Hint", wrap=True))
        self.sync_status = label("", "Muted", wrap=True)
        self.sync_status.setTextFormat(Qt.RichText)
        self.sync_status.setOpenExternalLinks(True)
        phone.lay.addWidget(self.sync_status)
        self.sync_btn = QPushButton()
        self.sync_btn.clicked.connect(self.toggle_sync)
        choose = QPushButton("Choose folder…")
        choose.clicked.connect(self.choose_sync_folder)
        self.sync_now = QPushButton("Sync now")
        self.sync_now.clicked.connect(lambda: self.ctx.sync_in(force=True) or self.ctx.toast("Up to date"))
        phone.lay.addLayout(hbox(self.sync_btn, choose, self.sync_now, None))
        self.body.addWidget(phone)

    def _build_data(self):
        data = Card()
        data.lay.addWidget(label("Backup & restore", "SectionTitle"))
        self.data_path = label("", "Hint", wrap=True)
        self.data_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        data.lay.addWidget(self.data_path)
        exp = QPushButton("Export backup…")
        exp.clicked.connect(self.ctx.export_backup)
        imp = QPushButton("Import backup…")
        imp.clicked.connect(self.ctx.import_backup)
        opn = QPushButton("Open data folder")
        opn.clicked.connect(self.open_folder)
        data.lay.addLayout(hbox(exp, imp, opn, None))
        data.lay.addWidget(label("A backup is saved automatically every day you make changes (the last 30 days "
                                 "are kept), plus a safety copy before every restore.", "Hint", wrap=True))
        self.auto = QComboBox()
        self.auto.setMinimumWidth(340)
        restore = QPushButton("Restore")
        restore.clicked.connect(self.restore_auto)
        data.lay.addLayout(hbox(self.auto, restore, None))
        rem = QPushButton("✉  Email && phone reminders…")
        rem.clicked.connect(self.ctx.notify_settings)
        cal = QPushButton("📅  Export to calendar…")
        cal.clicked.connect(self.ctx.calendar_export)
        data.lay.addLayout(hbox(rem, cal, label("Get reminded to pay your card and bills.", "Hint"), None))
        reset = QPushButton("Erase all data…")
        reset.setObjectName("Danger")
        reset.clicked.connect(self.ctx.reset_all)
        data.lay.addLayout(hbox(None, reset))
        self.body.addWidget(data)

    def _build_about(self):
        about = Card()
        about.lay.addWidget(label(f"Balance Tracker {__version__}", "SectionTitle"))
        self.update_status = label("", "Hint", wrap=True)
        self.update_status.setTextFormat(Qt.RichText)
        self.update_status.setOpenExternalLinks(True)
        self.update_btn = QPushButton("Check for updates")
        self.update_btn.clicked.connect(self.check_updates)
        keys = QPushButton("Keyboard shortcuts  (F1)")
        keys.clicked.connect(self.ctx.show_shortcuts)
        about.lay.addLayout(hbox(self.update_btn, keys, None))
        about.lay.addWidget(self.update_status)
        self.update_status.hide()
        self.body.addWidget(about)

    # ---- state -----------------------------------------------------------
    def refresh(self):
        self._loading = True
        s, d = self.ctx.data.settings, self.ctx.data
        self.account.setText(s.account_name)
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.theme)))
        self.currency.setText(s.currency_symbol)
        self.cushion.setPrefix(money.symbol())
        self.cushion.set_cents(s.low_balance_threshold)
        self.horizon.setValue(s.forecast_months)
        self.prompt.setChecked(s.prompt_on_open)
        if d.start:
            self.start_bal.set_cents(d.start.balance)
            self.start_date.setDate(d.start.date)
        self.start_bal.setPrefix(money.symbol())
        log_file = self.ctx.store.folder / logs.LOG_FILE
        self.data_path.setText(f"Your data is stored at: {self.ctx.store.path}\n"
                               f"If something goes wrong, details are written to {log_file}")
        self._refresh_sync()
        self.auto.clear()
        for b in self.ctx.store.backups():
            self.auto.addItem(b.label, str(b.path))
        if self.auto.count() == 0:
            self.auto.addItem("No backups yet", None)
        self._loading = False

    def _set(self, name: str, value) -> None:
        """Save one setting the user just changed."""
        s = self.ctx.data.settings
        if self._loading or getattr(s, name) == value:
            return
        setattr(s, name, value)
        self.ctx.commit(theme_changed=name == "theme")

    def _refresh_sync(self):
        s = self.ctx.data.settings
        app_link = (f"<br>Phone app: <a href='{WEB_APP_URL}'>{WEB_APP_URL}</a> — open it in Safari, then "
                    "Share → Add to Home Screen." if WEB_APP_URL else "")
        if s.sync_enabled and s.sync_folder:
            err = self.ctx.sync_error
            problem = (f"<br><span style='color:{theme.colors()['negative']}'>Problem: {escape(err)}</span>"
                       if err else "")
            self.sync_status.setText(f"✓ On — syncing through <b>{escape(s.sync_folder)}</b>{problem}"
                                     "<br>On your iPhone: Files → iCloud Drive → Balance Tracker." + app_link)
            self.sync_btn.setText("Turn off")
        else:
            icloud = sync.icloud_drive()
            self.sync_status.setText(
                (f"iCloud Drive found at <b>{escape(str(icloud))}</b>." if icloud else
                 "iCloud Drive isn't set up on this PC yet. Install <b>iCloud for Windows</b> from the Microsoft "
                 "Store, sign in with your Apple ID and tick <b>iCloud Drive</b> — then come back here.")
                + app_link)
            self.sync_btn.setText("Turn on iPhone sync")
        self.sync_btn.setObjectName("" if s.sync_enabled else "Primary")
        repolish(self.sync_btn)
        self.sync_now.setVisible(s.sync_enabled)

    # ---- actions ---------------------------------------------------------
    def toggle_sync(self):
        s = self.ctx.data.settings
        if s.sync_enabled:
            self.ctx.enable_sync(None)
            return
        default = sync.default_sync_folder()
        folder = s.sync_folder or (str(default) if default else "")
        if not folder:
            QMessageBox.information(
                self.widget, "Set up iCloud Drive first",
                "1. Install “iCloud for Windows” from the Microsoft Store.\n"
                "2. Sign in with your Apple ID and tick iCloud Drive.\n"
                "3. Come back and click “Turn on iPhone sync”.\n\n"
                "Or click “Choose folder…” to pick any folder your iPhone can see (e.g. OneDrive).")
            return
        self.ctx.enable_sync(folder)

    def choose_sync_folder(self):
        folder = QFileDialog.getExistingDirectory(self.widget, "Folder to sync with your iPhone",
                                                  str(sync.icloud_drive() or ""))
        if folder:
            self.ctx.enable_sync(folder)

    def save_start(self):
        d = self.start_date.value()
        in_the_way = [c for c in self.ctx.data.checkpoints if c.date <= d and c is not self.ctx.data.start]
        if in_the_way:
            QMessageBox.warning(self.widget, "Check-ins in the way",
                                "There are check-ins on or before that date. Delete them first, or pick an "
                                "earlier date.")
            return
        self.ctx.set_start(d, self.start_bal.cents())

    def open_folder(self):
        folder = self.ctx.store.folder
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(folder))  # noqa: S606 - opening our own data folder in Explorer
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def restore_auto(self):
        path = self.auto.currentData()
        if path:
            self.ctx.restore_from(path)

    def check_updates(self):
        self.update_btn.setEnabled(False)
        self.update_status.setText("Checking…")
        self.update_status.show()
        run_in_background(self.widget, updates.latest_release, self._update_checked)

    def _update_checked(self, release: updates.Release | None, error: Exception | None):
        self.update_btn.setEnabled(True)
        if error is not None:
            self.update_status.setText("Couldn't reach GitHub to check for updates. Check your internet "
                                       f"connection, or visit <a href='{updates.RELEASES_URL}'>the releases page</a>.")
        elif updates.is_newer(release.version):
            self.update_status.setText(f"<b>Version {escape(release.version)} is available.</b> "
                                       f"<a href='{escape(release.url)}'>Download it from GitHub</a>, then replace "
                                       "BalanceTracker.exe — your data is kept.")
        else:
            self.update_status.setText(f"You're up to date (version {__version__}).")
