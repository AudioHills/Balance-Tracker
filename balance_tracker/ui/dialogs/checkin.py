"""The balance check-in, and the first-run welcome that records the starting balance."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtWidgets import QCheckBox, QFrame, QLineEdit, QVBoxLayout

from ... import money
from ...forecast import Forecast, occurrences
from ...models import AppData, Checkpoint
from .. import theme
from ..widgets import DateField, MoneySpin, hbox, label
from .base import BaseDialog, form


class CheckInDialog(BaseDialog):
    """Enter the real bank balance; the gap vs. the plan becomes unplanned spending.
    On accept, the new check-in is in `result_checkpoint`."""

    def __init__(self, data: AppData, today: date | None = None, parent=None,
                 builder: Callable[..., Forecast] | None = None):
        super().__init__("Balance check-in",
                         "What does your bank show right now? Any difference from the plan is "
                         "logged as unplanned spending (or income) and the forecast is re-anchored.",
                         parent)
        self.data = data
        self.builder = builder
        self.today = today or date.today()
        self.setMinimumWidth(560)

        self.when = DateField(self.today)
        if data.start:
            self.when.setMinimumDate(min(data.start.date, self.today))
        self.when.setMaximumDate(self.today)
        self.balance = MoneySpin(allow_negative=True)
        self.includes = QCheckBox("This balance already includes that day's scheduled items")
        self.includes.setChecked(True)
        self.items_label = label("", "Hint", wrap=True)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional note — e.g. groceries, gas, birthday gift")

        f = form()
        f.addRow("Date", hbox(self.when, None))
        f.addRow("Actual balance", hbox(self.balance, None))
        f.addRow("", self.includes)
        f.addRow("", self.items_label)
        f.addRow("Note", self.note)
        self.outer.addLayout(f)

        box = QFrame()
        box.setObjectName("Card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 14, 16, 14)
        self.projected_lbl = label("", "Muted")
        self.diff_lbl = label("", "StatValue")
        self.diff_sub = label("", "Hint", wrap=True)
        self.after_lbl = label("", "Muted", wrap=True)
        for w in (self.projected_lbl, self.diff_lbl, self.diff_sub, self.after_lbl):
            bl.addWidget(w)
        self.outer.addWidget(box)
        self.add_buttons("Save check-in")

        self.when.dateChanged.connect(self._refresh)
        self.balance.valueChanged.connect(self._refresh)
        self.includes.toggled.connect(self._refresh)
        self._refresh(initial=True)
        self.balance.setFocus()

    def _projected(self):
        """(day, balance before that day's items, balance after them, that day's scheduled occurrences)."""
        d = self.when.value()
        # Project without any check-in already saved for this day, so re-checking in works.
        temp = AppData(items=self.data.items, debts=self.data.debts,
                       checkpoints=[c for c in self.data.checkpoints if c.date != d], settings=self.data.settings)
        f = self.builder(data=temp, end=d) if self.builder else Forecast(temp, d)
        todays = [o for i in self.data.items for o in occurrences(i, d, d)]
        return d, f.balance_before(d), f.balance_on(d), todays

    def _refresh(self, *_, initial: bool = False):
        d, before, after, todays = self._projected()
        self.includes.setVisible(bool(todays))
        what = ", ".join(f"{o.item.name} {money.fmt(o.amount, signed=True)}" for o in todays)
        if todays:
            self.includes.setText(f"{what} has already gone through" if len(todays) == 1
                                  else "These have already gone through")
            self.items_label.setText(
                (f"Scheduled that day: {what}. " if len(todays) > 1 else "")
                + "Untick this if " + ("they haven't" if len(todays) > 1 else "it hasn't") + " hit your account yet.")
        self.items_label.setVisible(bool(todays))
        pending = (after - before) if after is not None and before is not None else 0
        projected = after if (self.includes.isChecked() or not todays) else before
        if initial and projected is not None:
            self.balance.set_cents(projected)
        if projected is None:
            self.projected_lbl.setText("This replaces your starting balance."
                                       if self.data.start and d == self.data.start.date
                                       else "No projection for this date.")
            for w in (self.diff_lbl, self.diff_sub, self.after_lbl):
                w.setText("")
            self._proj = None
            return
        self._proj = projected
        diff = self.balance.cents() - projected
        self.projected_lbl.setText(f"The plan expected {money.fmt(projected)}")
        day_word = "Balance today" if d == self.today else "That day"
        if todays and not self.includes.isChecked() and pending:
            names = " and ".join(o.item.name for o in todays)
            self.after_lbl.setText(f"{day_word} will show {money.fmt(self.balance.cents() + pending)} once {names} "
                                   f"{'comes out' if pending < 0 else 'comes in'}.")
        else:
            self.after_lbl.setText(f"{day_word} will show {money.fmt(self.balance.cents())}.")
        col = theme.colors()
        if diff < 0:
            self.diff_lbl.setText(f"{money.fmt(-diff)} unplanned spending")
            self.diff_lbl.setStyleSheet(f"color: {col['negative']};")
            self.diff_sub.setText("Money spent outside your listed bills since the last check-in.")
        elif diff > 0:
            self.diff_lbl.setText(f"{money.fmt(diff)} more than planned")
            self.diff_lbl.setStyleSheet(f"color: {col['positive']};")
            self.diff_sub.setText("Extra income, a refund, or a bill that hasn't come out yet.")
        else:
            self.diff_lbl.setText("Right on plan")
            self.diff_lbl.setStyleSheet(f"color: {col['positive']};")
            self.diff_sub.setText("Nice — your balance matches the forecast exactly.")

    def accept(self):
        self.result_checkpoint = Checkpoint(date=self.when.value(), balance=self.balance.cents(),
                                            includes_today=self.includes.isChecked(), note=self.note.text().strip())
        super().accept()


class WelcomeDialog(BaseDialog):
    """First run: account name and starting balance (`result_account`, `result_checkpoint`)."""

    def __init__(self, parent=None, today: date | None = None):
        super().__init__("Welcome to Balance Tracker 👋",
                         "Let's start with what's in your chequing account today. You'll add your "
                         "paycheques and bills next, and Balance Tracker will forecast every day ahead.",
                         parent)
        self.setMinimumWidth(480)
        self.account = QLineEdit("Chequing")
        self.balance = MoneySpin(allow_negative=True)
        self.when = DateField(today or date.today())
        self.includes = QCheckBox("Anything scheduled today has already landed")
        self.includes.setChecked(True)
        f = form()
        f.addRow("Account name", self.account)
        f.addRow("Current balance", hbox(self.balance, None))
        f.addRow("As of", hbox(self.when, None))
        f.addRow("", self.includes)
        self.outer.addLayout(f)
        self.outer.addWidget(label("Tip: already have a backup? Cancel this and use "
                                   "Settings → Import backup.", "Hint", wrap=True))
        self.add_buttons("Get started")
        self.balance.setFocus()

    def accept(self):
        self.result_checkpoint = Checkpoint(date=self.when.value(), balance=self.balance.cents(),
                                            includes_today=self.includes.isChecked(), note="Starting balance")
        self.result_account = self.account.text().strip() or "Chequing"
        super().accept()
