"""Passwords: the app lock screen and its setup, the sync passphrase, and backup passwords."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ... import applock, encryption
from .. import theme
from ..icon import app_icon
from ..widgets import hbox, label
from .base import BaseDialog, form

IDLE_LABELS = {0: "Never", 1: "After 1 minute", 5: "After 5 minutes", 15: "After 15 minutes",
               30: "After 30 minutes", 60: "After 1 hour"}


def password_field(placeholder: str = "") -> QLineEdit:
    f = QLineEdit()
    f.setEchoMode(QLineEdit.Password)
    f.setPlaceholderText(placeholder)
    f.setMinimumWidth(300)
    return f


def ask_password(parent, title: str, text: str, problem: str = "") -> str | None:
    """A password prompt. Returns None if cancelled."""
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(f"{problem}\n\n{text}" if problem else text)
    dlg.setTextEchoMode(QLineEdit.Password)
    for lb in dlg.findChildren(QLabel):
        lb.setTextFormat(Qt.PlainText)
    return dlg.textValue() if dlg.exec() else None


class LockScreen(QDialog):
    """Shown at start-up and whenever the app locks. Accepts only the right password."""

    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.setWindowTitle("Balance Tracker — locked")
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.setContentsMargins(32, 28, 32, 24)
        v.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(56, 56))
        logo.setAlignment(Qt.AlignHCenter)
        v.addWidget(logo)
        title = label("Balance Tracker is locked", "PageTitle")
        title.setAlignment(Qt.AlignHCenter)
        v.addWidget(title)
        self.password = password_field("Password")
        self.password.returnPressed.connect(self.try_unlock)
        v.addWidget(self.password)
        self.message = label("", "Hint", wrap=True)
        self.message.setAlignment(Qt.AlignHCenter)
        v.addWidget(self.message)
        self.unlock_btn = QPushButton("Unlock")
        self.unlock_btn.setObjectName("Primary")
        self.unlock_btn.clicked.connect(self.try_unlock)
        forgot = QPushButton("Forgot password?")
        forgot.setObjectName("Chip")
        forgot.clicked.connect(self.forgot)
        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(self.reject)
        v.addLayout(hbox(forgot, None, quit_btn, self.unlock_btn))
        self.timer = QTimer(self, interval=1000, timeout=self._update_wait)
        self._update_wait()

    def _update_wait(self):
        cfg = applock.load(self.folder)
        wait = cfg.wait_seconds() if cfg else 0
        self.password.setEnabled(not wait)
        self.unlock_btn.setEnabled(not wait)
        if wait:
            self.message.setStyleSheet(f"color: {theme.colors()['negative']};")
            self.message.setText(f"Too many wrong passwords — try again in {wait} s")
            self.timer.start()
        else:
            self.timer.stop()
            if self.message.text().startswith("Too many"):
                self.message.setText("")
            self.password.setFocus()

    def try_unlock(self):
        if not self.password.isEnabled():
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = applock.check(self.folder, self.password.text())
        finally:
            QGuiApplication.restoreOverrideCursor()
        if ok:
            self.password.clear()
            self.accept()
            return
        self.password.clear()
        self.message.setStyleSheet(f"color: {theme.colors()['negative']};")
        self.message.setText("Wrong password")
        self._update_wait()

    def forgot(self):
        QMessageBox.information(
            self, "Forgot your password?",
            "The lock stops other people who use this PC from opening Balance Tracker. It doesn't encrypt "
            "your data, so you can't lose anything by removing it.\n\n"
            f"To remove the lock: quit Balance Tracker, open the folder\n{self.folder}\nand delete the file "
            "“secrets.json”. Then open Balance Tracker and set a new password in Settings. You'll also need to "
            "re-enter your email app password and iPhone sync passphrase, which are kept in the same file.")


class LockSetupDialog(BaseDialog):
    """Set or change the app lock password and when it locks by itself."""

    def __init__(self, folder, cfg: applock.LockConfig | None, parent=None):
        super().__init__("Lock Balance Tracker" if cfg is None else "Change the lock",
                         "Ask for a password when Balance Tracker opens and after you've been away, so other "
                         "people who use this PC can't see your finances.", parent)
        self.folder, self.cfg = folder, cfg
        self.setMinimumWidth(560)
        self.current = password_field("Your current password")
        self.new = password_field(f"At least {applock.MIN_PASSWORD} characters")
        self.confirm = password_field()
        self.idle = QComboBox()
        for minutes, text in IDLE_LABELS.items():
            self.idle.addItem(text, minutes)
        self.idle.setCurrentIndex(max(0, self.idle.findData(cfg.idle_minutes if cfg else 5)))
        self.minimize = QCheckBox("Also lock when I minimize the window")
        self.minimize.setChecked(bool(cfg and cfg.lock_on_minimize))
        f = form()
        if cfg is not None:
            f.addRow("Current password", self.current)
        f.addRow("New password" if cfg else "Password", self.new)
        f.addRow("Confirm", self.confirm)
        f.addRow("Lock automatically", hbox(self.idle, None))
        f.addRow("", self.minimize)
        self.outer.addLayout(f)
        if cfg is not None:
            self.outer.addWidget(label("Leave the new password blank to keep your current one.", "Hint", wrap=True))
        self.outer.addWidget(label("Press Ctrl+L to lock straight away. Your data file is protected by your Windows "
                                   "sign-in; to protect it if the PC is lost or stolen, turn on BitLocker or Device "
                                   "encryption in Windows Settings.", "Hint", wrap=True))
        self.add_buttons("Save")

    def accept(self):
        if self.cfg is not None and not applock.check(self.folder, self.current.text()):
            wait = (applock.load(self.folder) or self.cfg).wait_seconds()
            QMessageBox.warning(self, "Current password",
                                f"Too many wrong passwords — try again in {wait} s." if wait
                                else "Your current password isn't right.")
            return
        new = self.new.text()
        if self.cfg is None or new:
            problem = applock.password_problem(new)
            if problem:
                QMessageBox.warning(self, "Password", problem)
                return
            if new != self.confirm.text():
                QMessageBox.warning(self, "Password", "The passwords don't match.")
                return
        idle, minimize = self.idle.currentData(), self.minimize.isChecked()
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if new:
                applock.set_password(self.folder, new, idle, minimize)
            else:
                cfg = applock.load(self.folder)
                cfg.idle_minutes, cfg.lock_on_minimize = idle, minimize
                applock.save(self.folder, cfg)
        finally:
            QGuiApplication.restoreOverrideCursor()
        super().accept()


class SyncPassphraseDialog(BaseDialog):
    """Choose the passphrase that encrypts the iPhone sync file. On accept it's in `result_passphrase`."""

    def __init__(self, parent=None):
        super().__init__("Encrypt the sync file",
                         "The sync file in iCloud Drive is encrypted with this passphrase, so Apple, anyone who "
                         "gets into your iCloud account, or anyone you share the folder with can't read it — and "
                         "nobody can slip a fake file in. You'll type it once on your iPhone.", parent)
        self.setMinimumWidth(600)
        self.result_passphrase = ""
        self.phrase = password_field(f"At least {encryption.MIN_PASSPHRASE} characters")
        self.confirm = password_field()
        self.show_it = QCheckBox("Show")
        self.show_it.toggled.connect(self._show)
        suggest = QPushButton("Suggest a strong one")
        suggest.clicked.connect(self._suggest)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.phrase.text()))
        f = form()
        f.addRow("Passphrase", hbox(self.phrase, self.show_it))
        f.addRow("Confirm", self.confirm)
        f.addRow("", hbox(suggest, copy_btn, None))
        self.outer.addLayout(f)
        self.outer.addWidget(label(
            "Keep it somewhere safe, like your password manager. If you forget it, just set a new one here and "
            "enter the new one on your iPhone — your data is kept on both devices. After saving, open the iPhone "
            "app, tap ⟳ → Choose sync file, and enter the passphrase when asked.", "Hint", wrap=True))
        self.add_buttons("Encrypt")

    def _show(self, on: bool):
        mode = QLineEdit.Normal if on else QLineEdit.Password
        self.phrase.setEchoMode(mode)
        self.confirm.setEchoMode(mode)

    def _suggest(self):
        p = encryption.suggest_passphrase()
        self.phrase.setText(p)
        self.confirm.setText(p)
        self.show_it.setChecked(True)

    def accept(self):
        p = self.phrase.text()
        problem = encryption.passphrase_problem(p)
        if problem:
            QMessageBox.warning(self, "Passphrase", problem)
            return
        if p != self.confirm.text():
            QMessageBox.warning(self, "Passphrase", "The passphrases don't match.")
            return
        self.result_passphrase = p
        super().accept()


class BackupPasswordDialog(BaseDialog):
    """Optional password for an exported backup. On accept it's in `result_password` ("" = none)."""

    def __init__(self, parent=None):
        super().__init__("Protect this backup?",
                         "A backup holds all your balances, bills and debts. Add a password so it's safe to keep "
                         "in email, cloud storage or a USB stick. You'll need it to restore the backup.", parent)
        self.setMinimumWidth(560)
        self.result_password = ""
        self.password = password_field(f"At least {encryption.MIN_PASSPHRASE} characters — or leave blank")
        self.confirm = password_field()
        f = form()
        f.addRow("Password", self.password)
        f.addRow("Confirm", self.confirm)
        self.outer.addLayout(f)
        self.outer.addWidget(label("Leave both blank to save an unprotected backup.", "Hint", wrap=True))
        self.add_buttons("Export")

    def accept(self):
        p = self.password.text()
        if p or self.confirm.text():
            problem = encryption.passphrase_problem(p)
            if problem:
                QMessageBox.warning(self, "Password", problem)
                return
            if p != self.confirm.text():
                QMessageBox.warning(self, "Password", "The passwords don't match.")
                return
        self.result_password = p
        super().accept()
