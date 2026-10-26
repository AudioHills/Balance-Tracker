"""Daily reminder emails and phone (ntfy) notifications."""
from __future__ import annotations

import copy
from datetime import date

from PySide6.QtCore import Qt, QTime, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ... import notify
from ...models import AppData
from .. import theme
from ..widgets import hbox, label
from ..workers import run_in_background
from .base import BaseDialog

TEST_COOLDOWN_MS = 20_000


class NotifyDialog(BaseDialog):
    """Daily reminder emails and phone (ntfy) notifications."""

    def __init__(self, data: AppData, folder, parent=None):
        super().__init__("Email & phone reminders",
                         "Get one short message on days something needs doing — e.g. “Pay Visa $11.99 — "
                         "Spotify”. Works even when Balance Tracker is closed (your PC just needs to be on "
                         "at some point that day).", parent)
        self.data, self.folder = data, folder
        s = data.settings
        self.setMinimumWidth(640)

        # --- email
        self.email_on = QCheckBox("Email me a daily summary")
        self.email_on.setChecked(s.email_enabled)
        self.to = QLineEdit(s.email_to)
        self.to.setPlaceholderText("you@gmail.com")
        self.provider = QComboBox()
        for name in notify.EMAIL_PRESETS:
            self.provider.addItem(name, name)
        self.provider.addItem("Other (enter server)", "other")
        match = next((n for n, (h, *_r) in notify.EMAIL_PRESETS.items() if h == s.smtp_host), None)
        self.provider.setCurrentIndex(self.provider.findData(match or "other"))
        self.user = QLineEdit(s.smtp_user)
        self.user.setPlaceholderText("Same as above")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.has_saved_pw = bool(notify.load_password(folder))
        self.password.setPlaceholderText("Saved — leave blank to keep" if self.has_saved_pw
                                         else "16-character app password")
        self.host = QLineEdit(s.smtp_host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(s.smtp_port)
        self.use_ssl = QCheckBox("SSL (usually port 465)")
        self.use_ssl.setChecked(s.smtp_ssl)
        self.help = label("", "Hint", wrap=True)
        self.help.setTextFormat(Qt.RichText)
        self.help.setOpenExternalLinks(True)

        ef = QFormLayout()
        ef.setLabelAlignment(Qt.AlignRight)
        ef.setVerticalSpacing(8)
        ef.addRow("", self.email_on)
        ef.addRow("Send to", self.to)
        ef.addRow("Email service", self.provider)
        ef.addRow("Sign in as", self.user)
        ef.addRow("App password", self.password)
        self.host_label = QLabel("Server")
        ef.addRow(self.host_label, hbox(self.host, self.port, self.use_ssl))
        ef.addRow("", self.help)

        # --- ntfy
        self.ntfy_on = QCheckBox("Also send a phone notification with the free ntfy app")
        self.ntfy_on.setChecked(s.ntfy_enabled)
        self.topic = QLineEdit(s.ntfy_topic or notify.new_ntfy_topic())
        self.topic.setMaxLength(64)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.topic.text()))
        new_btn = QPushButton("New random topic")
        new_btn.setToolTip("Pick a new unguessable topic (then subscribe to it again in the ntfy app)")
        new_btn.clicked.connect(lambda: self.topic.setText(notify.new_ntfy_topic()))
        nf = QFormLayout()
        nf.setLabelAlignment(Qt.AlignRight)
        nf.setVerticalSpacing(8)
        nf.addRow("", self.ntfy_on)
        nf.addRow("Topic", hbox(self.topic, copy_btn, new_btn))
        nf.addRow("", label("Install <b>ntfy</b> from the Play Store or App Store → tap <b>+</b> → "
                            "<b>Subscribe to topic</b> → paste the topic above. Messages go through the public "
                            "ntfy.sh service, where <b>anyone who knows the topic can read them</b> — keep it "
                            "random and private, like a password.",
                            "Hint", wrap=True, rich=True))

        # --- content + timing
        self.n_card = QCheckBox("Pay-your-card reminders (bills charged to a credit card)")
        self.n_debts = QCheckBox("Debt payments due (from your payoff plan)")
        self.n_bills = QCheckBox("Bills coming out of chequing")
        self.n_pay = QCheckBox("Paydays")
        self.n_low = QCheckBox("Low balance warnings (within the next week)")
        for w, v in ((self.n_card, s.notify_card), (self.n_debts, s.notify_debts), (self.n_bills, s.notify_bills),
                     (self.n_pay, s.notify_paydays), (self.n_low, s.notify_low)):
            w.setChecked(v)
        self.before = QSpinBox()
        self.before.setRange(0, 7)
        self.before.setValue(s.notify_days_before)
        self.before.setSpecialValueText("Day of only")
        self.before.setSuffix(" day(s) ahead too")
        self.time = QTimeEdit(QTime.fromString(s.notify_time, "HH:mm"))
        self.time.setDisplayFormat("h:mm AP")
        self.time.setButtonSymbols(QTimeEdit.NoButtons)
        self.background = QCheckBox("Send even when Balance Tracker is closed (adds a Windows scheduled task)")
        self.background.setChecked(s.notify_task or not (s.email_enabled or s.ntfy_enabled))

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.setSpacing(10)
        bl.addWidget(label("Email", "SectionTitle"))
        bl.addLayout(ef)
        bl.addWidget(label("Phone notification (optional)", "SectionTitle"))
        bl.addLayout(nf)
        bl.addWidget(label("What to include", "SectionTitle"))
        for w in (self.n_card, self.n_debts, self.n_bills, self.n_pay, self.n_low):
            bl.addWidget(w)
        tf = QFormLayout()
        tf.setLabelAlignment(Qt.AlignRight)
        tf.addRow("Bills & debt payments", hbox(self.before, None))
        tf.addRow("Send at", hbox(self.time, None))
        bl.addLayout(tf)
        bl.addWidget(self.background)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setMinimumHeight(460)
        self.outer.addWidget(scroll, 1)

        last = notify.last_log(folder)
        self.status = label(f"Last activity: {last}" if last else "", "Hint", wrap=True)
        self.outer.addWidget(self.status)
        bb = self.add_buttons("Save")
        self.test_btn = bb.addButton("Send a test now", QDialogButtonBox.ActionRole)
        self.test_btn.clicked.connect(self.send_test)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed(initial=True)
        self.resize(680, 760)

    def _provider_changed(self, *_, initial=False):
        key = self.provider.currentData()
        other = key == "other"
        for w in (self.host, self.port, self.use_ssl, self.host_label):
            w.setVisible(other)
        if not other and not (initial and self.host.text() == notify.EMAIL_PRESETS[key][0]):
            host, port, use_ssl = notify.EMAIL_PRESETS[key]
            self.host.setText(host)
            self.port.setValue(port)
            self.use_ssl.setChecked(use_ssl)
        tips = {
            "Gmail": "Gmail needs an <b>app password</b> (your normal password won't work): turn on "
                     "2-Step Verification, then visit "
                     "<a href='https://myaccount.google.com/apppasswords'>myaccount.google.com/apppasswords</a>, "
                     "create one named “Balance Tracker” and paste the 16 letters here.",
            "Outlook / Hotmail": "Create an app password under Microsoft account → Security → Advanced security "
                                 "options → App passwords. If Outlook refuses the sign-in, use a Gmail account "
                                 "to send instead (it can still send to your Outlook address).",
            "Yahoo": "Create an app password under Yahoo Account Security → Generate app password.",
            "iCloud": "Create an app-specific password at appleid.apple.com → Sign-In and Security.",
            "other": "Use your provider's SMTP server details.",
        }
        self.help.setText(tips.get(key, "") + "<br>The password is encrypted with Windows' own protection and "
                                              "is never included in backups.")

    def _apply(self, s):
        s.email_enabled = self.email_on.isChecked()
        s.email_to = self.to.text().strip()
        s.smtp_user = self.user.text().strip() or s.email_to
        s.smtp_host = self.host.text().strip()
        s.smtp_port = self.port.value()
        s.smtp_ssl = self.use_ssl.isChecked()
        s.ntfy_enabled = self.ntfy_on.isChecked()
        s.ntfy_topic = self.topic.text().strip()
        s.notify_card = self.n_card.isChecked()
        s.notify_debts = self.n_debts.isChecked()
        s.notify_bills = self.n_bills.isChecked()
        s.notify_paydays = self.n_pay.isChecked()
        s.notify_low = self.n_low.isChecked()
        s.notify_days_before = self.before.value()
        s.notify_time = self.time.time().toString("HH:mm")

    def _validate(self) -> bool:
        if self.email_on.isChecked():
            if "@" not in self.to.text():
                QMessageBox.warning(self, "Email address", "Enter the email address to send reminders to.")
                return False
            if not self.password.text() and not self.has_saved_pw:
                QMessageBox.warning(self, "App password", "Enter the app password for the sending account.")
                return False
        problem = notify.ntfy_topic_problem(self.topic.text().strip())
        if self.ntfy_on.isChecked() and problem:
            QMessageBox.warning(self, "Topic", problem)
            return False
        return True

    def send_test(self):
        if not self._validate():
            return
        if not (self.email_on.isChecked() or self.ntfy_on.isChecked()):
            QMessageBox.information(self, "Nothing to test", "Turn on email or phone notifications first.")
            return
        trial = copy.deepcopy(self.data)
        self._apply(trial.settings)
        if self.password.text():
            notify.save_password(self.folder, self.password.text())
            self.has_saved_pw = True
        digest = notify.compose(trial, date.today()) or notify.Digest(
            "Test from Balance Tracker ✓", [("✅", "Reminders are set up. Nothing is due today.", False)])
        digest.subject = "[Test] " + digest.subject
        self.test_btn.setEnabled(False)
        self.status.setStyleSheet("")
        self.status.setText("Sending a test…")
        run_in_background(self, lambda: notify.deliver(trial, self.folder, digest), self._test_done)

    def _test_done(self, errors: list | None, crash: Exception | None):
        # A short cooldown, so a stuck button can't fire off a burst of emails from your account
        QTimer.singleShot(TEST_COOLDOWN_MS, lambda: self.test_btn.setEnabled(True))
        col = theme.colors()
        errors = [str(crash)] if crash else errors
        if errors:
            self.status.setStyleSheet(f"color: {col['negative']};")
            self.status.setText("Couldn't send: " + " · ".join(errors) +
                                "\nCheck the address and app password (not your normal password).")
        else:
            self.status.setStyleSheet(f"color: {col['positive']};")
            self.status.setText("✓ Test sent — check your inbox (and spam folder) or the ntfy app.")

    def accept(self):
        if not self._validate():
            return
        self._apply(self.data.settings)
        if self.password.text():
            notify.save_password(self.folder, self.password.text())
        self.want_task = self.background.isChecked() and (self.email_on.isChecked() or self.ntfy_on.isChecked())
        super().accept()
