"""Export reminders as a calendar (.ics) file for the phone."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QCheckBox, QFileDialog, QMessageBox, QSpinBox, QTimeEdit

from ...models import AppData
from ...reminders import collect, to_ics
from ..widgets import hbox, label
from .base import BaseDialog, form


class RemindersDialog(BaseDialog):
    """Export reminders as a calendar file the phone can import."""

    def __init__(self, data: AppData, plan, today: date, parent=None):
        super().__init__("Phone reminders 📱",
                         "Save a calendar file and add it to your phone's calendar. Your phone will alert "
                         "you — even when this computer is off.", parent)
        self.data, self.plan, self.today = data, plan, today
        self.setMinimumWidth(620)
        has_cards = any(i.paid_with for i in data.items)
        self.card = QCheckBox("Pay-your-card reminders for bills charged to a credit card")
        self.card.setChecked(has_cards)
        self.card.setEnabled(has_cards)
        if not has_cards:
            self.card.setToolTip("Edit a bill and set “Paid with” to a credit card to use this.")
        self.debts = QCheckBox("Debt payment due dates from your payoff plan")
        self.debts.setChecked(bool(plan and plan.payments))
        self.debts.setEnabled(bool(plan and plan.payments))
        self.bills = QCheckBox("Bills paid from chequing")
        self.paydays = QCheckBox("Paydays")
        self.time = QTimeEdit(QTime.fromString(data.settings.reminder_time, "HH:mm"))
        self.time.setDisplayFormat("h:mm AP")
        self.time.setButtonSymbols(QTimeEdit.NoButtons)
        self.before = QSpinBox()
        self.before.setRange(0, 7)
        self.before.setValue(1)
        self.before.setSpecialValueText("No")
        self.before.setSuffix(" day(s) before")
        self.months = QSpinBox()
        self.months.setRange(1, 24)
        self.months.setValue(6)
        self.months.setSuffix(" months")
        for w in (self.card, self.debts, self.bills, self.paydays):
            self.outer.addWidget(w)
        f = form()
        f.addRow("Remind me at", hbox(self.time, None))
        f.addRow("Heads-up", hbox(self.before, label("for debt payments and bills", "Hint"), None))
        f.addRow("Cover the next", hbox(self.months, None))
        self.outer.addLayout(f)
        self.count = label("", "SectionTitle")
        self.outer.addWidget(self.count)
        self.outer.addWidget(self._howto(
            "<b>Getting it onto your phone</b><br>"
            "• <b>Google Calendar</b> (Android or iPhone): on a computer go to calendar.google.com → ⚙ Settings → "
            "Import &amp; export → choose the file. Tip: create a calendar called “Bills” first and import into it.<br>"
            "• <b>iPhone Calendar</b>: email the file to yourself, open the attachment on your iPhone → Add All.<br>"
            "• <b>Outlook</b>: double-click the file, or Calendar → Add calendar → Upload from file.<br>"
            "Re-export whenever your bills or plan change — events with the same ID are updated, not duplicated."))
        self.add_buttons("Save calendar file…")
        for w in (self.card, self.debts, self.bills, self.paydays):
            w.toggled.connect(self._refresh)
        self.before.valueChanged.connect(self._refresh)
        self.months.valueChanged.connect(self._refresh)
        self._refresh()

    @staticmethod
    def _howto(html: str):
        lb = label(html, "Hint", wrap=True, rich=True)
        lb.setMinimumHeight(lb.heightForWidth(572) + 8)
        return lb

    def _collect(self):
        return collect(self.data, self.plan, self.today, self.months.value(), self.card.isChecked(),
                       self.debts.isChecked(), self.bills.isChecked(), self.paydays.isChecked(),
                       self.before.value())

    def _refresh(self):
        n = len(self._collect())
        self.count.setText(f"{n} reminder{'s' if n != 1 else ''} will be added")

    def accept(self):
        items = self._collect()
        if not items:
            QMessageBox.information(self, "Nothing to export", "Tick at least one kind of reminder.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save reminders", "BalanceTracker-reminders.ics",
                                              "Calendar file (*.ics)")
        if not path:
            return
        self.data.settings.reminder_time = self.time.time().toString("HH:mm")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(to_ics(items, self.data.settings.reminder_time))
        self.saved_path = path
        self.saved_count = len(items)
        super().accept()
