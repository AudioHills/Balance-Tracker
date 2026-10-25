"""Add/edit an income or bill, and change an entry's amount from a date on."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox

from ... import money
from ...forecast import change_amount_from, next_occurrence, occurrences, scheduled_dates, shift_weekend
from ...formatting import full_date, short_date
from ...models import BILL, FREQUENCIES, INCOME, LAST_DAY, WEEKEND_RULES, AppData, RecurringItem
from ..widgets import DateField, MoneySpin, chips, chosen, hbox, label, select_chip
from .base import BaseDialog, form


class ItemDialog(BaseDialog):
    """Add or edit an income / bill. On accept, the new version is in `result_item`."""

    def __init__(self, data: AppData, item: RecurringItem | None = None, kind: str = BILL, parent=None,
                 today: date | None = None, title: str | None = None, ok_text: str | None = None):
        editing = item is not None
        kind = item.kind if item else kind
        super().__init__(title or ("Edit entry" if editing else ("Add income" if kind == INCOME else "Add bill")),
                         "Set it once — Balance Tracker works out every future date for you.", parent)
        self.item = item
        self.today = today or date.today()
        self.setMinimumWidth(500)

        self.kind_btns = chips([("Income", INCOME), ("Bill / expense", BILL)], self._refresh, self)
        select_chip(self.kind_btns, kind)
        self.btn_income, self.btn_bill = self.kind_btns
        self.name = QLineEdit(item.name if item else "")
        self.name.setPlaceholderText("e.g. Paycheque, Rent, Netflix")
        self.amount = MoneySpin()
        if item:
            self.amount.set_cents(item.amount)
        self.paid_with = QComboBox()
        self.paid_with.addItem("Chequing account", "")
        for dbt in data.debts:
            if dbt.kind != "loan":
                self.paid_with.addItem(f"💳 {dbt.name} — I pay it off right away", dbt.id)
        if item and item.paid_with:
            self.paid_with.setCurrentIndex(max(0, self.paid_with.findData(item.paid_with)))
        self.paid_with.setToolTip("Bills charged to a credit card show up as “Pay <card>” on the same day, "
                                  "and can remind your phone to pay the card right away.")
        self.freq = QComboBox()
        for k, v in FREQUENCIES.items():
            self.freq.addItem(v, k)
        self.freq.setCurrentIndex(list(FREQUENCIES).index(item.frequency if item else "monthly"))
        self.start = DateField(item.start_date if item else self.today)
        self.second = QSpinBox()
        self.second.setRange(1, 31)
        self.second.setValue(item.second_day if item else LAST_DAY)
        self.second_hint = label("31 = last day of the month", "Hint")
        self.has_end = QCheckBox("Stops on")
        self.end = DateField(item.end_date if item and item.end_date else self.today + timedelta(days=365))
        self.has_end.setChecked(bool(item and item.end_date))
        self.weekend = QComboBox()
        for k, v in WEEKEND_RULES.items():
            self.weekend.addItem(v, k)
        self.weekend.setCurrentIndex(list(WEEKEND_RULES).index(item.weekend_rule if item else "none"))
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems([""] + data.categories())
        self.category.setCurrentText(item.category if item else "")
        self.category.lineEdit().setPlaceholderText("Optional — e.g. Housing, Utilities")
        self.notes = QPlainTextEdit(item.notes if item else "")
        self.notes.setFixedHeight(56)
        self.active = QCheckBox("Include in forecast")
        self.active.setChecked(item.active if item else True)

        f = form()
        f.addRow("Type", hbox(*self.kind_btns, None))
        f.addRow("Name", self.name)
        f.addRow("Amount", hbox(self.amount, None))
        self.paid_label = QLabel("Paid with")
        f.addRow(self.paid_label, self.paid_with)
        f.addRow("How often", self.freq)
        self.start_label = QLabel("Date")
        f.addRow(self.start_label, hbox(self.start, None))
        self.second_row_label = QLabel("Second day")
        f.addRow(self.second_row_label, hbox(self.second, self.second_hint, None))
        f.addRow("", hbox(self.has_end, self.end, None))
        f.addRow("On weekends", self.weekend)
        f.addRow("Category", self.category)
        f.addRow("Notes", self.notes)
        f.addRow("", self.active)
        self.outer.addLayout(f)

        self.preview = label("", "Hint", wrap=True)
        self.outer.addWidget(self.preview)
        self.add_buttons(ok_text or ("Save" if editing else "Add"))

        for sig in (self.freq.currentIndexChanged, self.start.dateChanged, self.second.valueChanged,
                    self.has_end.toggled, self.end.dateChanged, self.weekend.currentIndexChanged):
            sig.connect(self._refresh)
        self._refresh()
        self.name.setFocus()

    def _build(self) -> RecurringItem:
        kind = chosen(self.kind_btns)
        it = RecurringItem(
            name=self.name.text().strip(),
            amount=self.amount.cents(),
            kind=kind,
            frequency=self.freq.currentData(),
            start_date=self.start.value(),
            end_date=self.end.value() if self.has_end.isChecked() else None,
            second_day=self.second.value(),
            weekend_rule=self.weekend.currentData(),
            category=self.category.currentText().strip(),
            notes=self.notes.toPlainText().strip(),
            active=self.active.isChecked(),
            paid_with=(self.paid_with.currentData() or "") if kind == BILL else "",
        )
        if self.item:
            it.id = self.item.id
            it.overrides = dict(self.item.overrides)
        return it

    def _refresh(self):
        show_card = chosen(self.kind_btns) == BILL and self.paid_with.count() > 1
        self.paid_with.setVisible(show_card)
        self.paid_label.setVisible(show_card)
        once = self.freq.currentData() == "once"
        self.start_label.setText("Date" if once else "First / next date")
        semi = self.freq.currentData() == "semimonthly"
        for w in (self.second, self.second_hint, self.second_row_label):
            w.setVisible(semi)
        self.has_end.setVisible(not once)
        self.end.setVisible(not once and self.has_end.isChecked())
        it = self._build()
        upcoming = []
        for sd in scheduled_dates(it, self.today + timedelta(days=800), since=self.today):
            post = shift_weekend(sd, it.weekend_rule)
            if post >= self.today:
                upcoming.append(short_date(post))
            if len(upcoming) == 5:
                break
        self.preview.setText(("Upcoming: " + "  ·  ".join(upcoming)) if upcoming
                             else "No upcoming dates for this schedule.")
        self.adjustSize()

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing name", "Please give this entry a name.")
            return
        if self.amount.cents() <= 0:
            QMessageBox.warning(self, "Missing amount", "Please enter an amount greater than zero.")
            return
        if self.has_end.isChecked() and self.end.value() < self.start.value():
            QMessageBox.warning(self, "Check the dates", "The end date is before the start date.")
            return
        self.result_item = self._build()
        super().accept()


class ChangeAmountDialog(BaseDialog):
    """Pick a new amount and the date it starts. On accept: `result_when` and `result_amount`."""

    def __init__(self, item: RecurringItem, today: date, when: date | None = None, parent=None):
        word = "pay" if item.kind == INCOME else "bill"
        super().__init__(f"Change “{item.name}”",
                         f"For a {word} that's changing from a certain date — a rent increase, a new phone plan, "
                         "a raise. Earlier dates keep the old amount and the schedule stays the same.", parent)
        self.item = item
        self.today = today
        self.setMinimumWidth(520)
        if when is None:
            nxt = next_occurrence(item, today)
            when = nxt.scheduled if nxt else today
        self.when = DateField(when)
        self.when.setMinimumDate(item.start_date)
        self.amount = MoneySpin()
        self.amount.set_cents(item.amount)
        f = form()
        f.addRow("Currently", label(f"{money.fmt(item.amount)} · {FREQUENCIES[item.frequency].lower()}", "Muted"))
        f.addRow("New amount", hbox(self.amount, None))
        f.addRow("Starting", hbox(self.when, None))
        self.outer.addLayout(f)
        self.preview = label("", "Hint", wrap=True)
        self.outer.addWidget(self.preview)
        self.add_buttons("Change amount")
        self.amount.valueChanged.connect(self._refresh)
        self.when.dateChanged.connect(self._refresh)
        self._refresh()
        self.amount.setFocus()

    def _refresh(self):
        when, cents = self.when.value(), self.amount.cents()
        head, tail = change_amount_from(self.item, when, cents)
        upcoming = sorted((o for it in (head, tail) if it for o in occurrences(it, when, when + timedelta(days=800))),
                          key=lambda o: o.date)[:4]
        if not upcoming:
            self.preview.setText("Nothing is scheduled on or after that date.")
            return
        dates = "  ·  ".join(f"{short_date(o.date)} {money.fmt(abs(o.amount))}" for o in upcoming)
        self.preview.setText(f"From {full_date(upcoming[0].date)} it will be {money.fmt(cents)} "
                             f"(was {money.fmt(self.item.amount)}).\nNext: {dates}")

    def accept(self):
        if self.amount.cents() <= 0:
            QMessageBox.warning(self, "Missing amount", "Please enter an amount greater than zero.")
            return
        self.result_when = self.when.value()
        self.result_amount = self.amount.cents()
        super().accept()

