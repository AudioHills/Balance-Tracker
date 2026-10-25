"""'Can I afford it?' — test a one-time purchase against the forecast."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from PySide6.QtWidgets import QDialogButtonBox, QFrame, QLineEdit, QMessageBox, QVBoxLayout

from ... import money
from ...forecast import Forecast, Occurrence, horizon_end
from ...formatting import long_date, month_day
from ...models import BILL, AppData, RecurringItem
from .. import theme
from ..widgets import DateField, MoneySpin, hbox, label
from .base import BaseDialog, form


def purchase(day: date, cents: int) -> Occurrence:
    """A one-off spend on `day`, as an extra forecast occurrence."""
    item = RecurringItem(name="Purchase", amount=cents, kind=BILL, frequency="once", start_date=day, id="")
    return Occurrence(day, day, -cents, item)


class AffordDialog(BaseDialog):
    """On accept ("Add it as a one-time bill"), the purchase is in `result_item`."""

    def __init__(self, data: AppData, builder: Callable[..., Forecast], today: date, parent=None):
        super().__init__("Can I afford it?",
                         "Try a purchase before you make it. Balance Tracker checks every day ahead "
                         "to see whether you'd stay above your cushion.", parent)
        self.data = data
        # Judge purchases against minimum debt payments only: in "auto" mode the debt plan
        # soaks up all spare money, and it shrinks its extra payments to fit new purchases.
        self.builder = lambda **kw: builder(debt_extras=False, **kw)
        self.plan_note = bool(data.debts) and data.settings.debt_in_forecast and data.settings.debt_mode == "auto"
        self.today = today
        self.setMinimumWidth(520)
        self.name = QLineEdit()
        self.name.setPlaceholderText("What is it? e.g. New tires")
        self.amount = MoneySpin()
        self.when = DateField(today)
        self.when.setMinimumDate(today)
        f = form()
        f.addRow("Purchase", self.name)
        f.addRow("Amount", hbox(self.amount, None))
        f.addRow("On", hbox(self.when, None))
        self.outer.addLayout(f)

        box = QFrame()
        box.setObjectName("Card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 14, 16, 14)
        self.verdict = label("", "StatValue", wrap=True)
        self.detail = label("", "Muted", wrap=True)
        self.tip = label("", "Hint", wrap=True)
        for w in (self.verdict, self.detail, self.tip):
            bl.addWidget(w)
        self.outer.addWidget(box)
        bb = self.add_buttons("Add it as a one-time bill")
        bb.button(QDialogButtonBox.Cancel).setText("Close")
        self.amount.valueChanged.connect(self._refresh)
        self.when.dateChanged.connect(self._refresh)
        self._base = self.builder()
        self._refresh()
        self.amount.setFocus()

    def _verdict(self, text: str, tone: str):
        self.verdict.setText(text)
        self.verdict.setStyleSheet(f"color: {theme.colors()[tone]};")

    def _refresh(self):
        cents, d = self.amount.cents(), self.when.value()
        cushion = self.data.settings.low_balance_threshold
        end = horizon_end(self.data, self.today)
        base_low = self._base.lowest(d, end)
        if base_low is None:
            self._verdict("Add a starting balance first", "muted")
            return
        if cents == 0:
            self._verdict(f"You can spend up to {money.fmt(max(0, base_low[1] - cushion))}", "accent")
            self.detail.setText(f"on {month_day(d)} and still keep your {money.fmt(cushion)} cushion "
                                f"through {end:%B %Y}.")
            self.tip.setText("")
            return
        low = self.builder(extra=[purchase(d, cents)]).lowest(d, end)
        if low[1] >= cushion:
            self._verdict("Yes — you can afford it ✓", "positive")
            self.detail.setText(f"Your lowest balance afterwards would be {money.fmt(low[1])} on "
                                f"{month_day(low[0])}, still above your {money.fmt(cushion)} cushion.")
            self.tip.setText("Your debt plan's extra payments will shrink a little to make room for it."
                             if self.plan_note else "")
        elif low[1] >= 0:
            self._verdict("Tight — it dips into your cushion", "warning")
            self.detail.setText(f"Your balance would fall to {money.fmt(low[1])} on {month_day(low[0])}.")
            self.tip.setText(self._later_tip(cents, d, cushion, end))
        else:
            self._verdict("Not right now ✕", "negative")
            self.detail.setText(f"You'd be overdrawn by {money.fmt(-low[1])} on {month_day(low[0])}.")
            self.tip.setText(self._later_tip(cents, d, cushion, end))

    def _later_tip(self, cents: int, d: date, cushion: int, end: date) -> str:
        """Find the first later date this purchase would fit."""
        day = d + timedelta(days=1)
        while day <= end:
            low = self._base.lowest(day, end)
            if low and low[1] - cents >= cushion and \
                    self.builder(extra=[purchase(day, cents)]).lowest(day, end)[1] >= cushion:
                return f"💡 It would fit if you wait until {long_date(day)}."
            day += timedelta(days=1)
        return "💡 It doesn't fit within your forecast window without dipping below your cushion."

    def accept(self):
        if self.amount.cents() <= 0:
            QMessageBox.information(self, "Enter an amount", "Enter the purchase amount first.")
            return
        self.result_item = RecurringItem(
            name=self.name.text().strip() or "Planned purchase", amount=self.amount.cents(), kind=BILL,
            frequency="once", start_date=self.when.value(), category="Planned purchase")
        super().accept()

