"""Dialogs: add/edit income or bill, balance check-in, first-run welcome."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from .. import money
from ..forecast import Forecast, occurrences, shift_weekend, scheduled_dates
from ..models import (
    AppData, BILL, Checkpoint, FREQUENCIES, INCOME, LAST_DAY, RecurringItem, WEEKEND_RULES,
)
from . import theme
from .widgets import MoneySpin, hbox, label


def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def from_qdate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def date_edit(d: date) -> QDateEdit:
    e = QDateEdit(to_qdate(d))
    e.setCalendarPopup(True)
    e.setDisplayFormat("ddd MMM d, yyyy")
    e.setMinimumWidth(170)
    return e


class BaseDialog(QDialog):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(24, 22, 24, 20)
        self.outer.setSpacing(14)
        self.outer.addWidget(label(title, "PageTitle"))
        if subtitle:
            self.outer.addWidget(label(subtitle, "PageSubtitle", wrap=True))

    def add_buttons(self, ok_text: str = "Save"):
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = bb.button(QDialogButtonBox.Ok)
        ok.setText(ok_text)
        ok.setObjectName("Primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.outer.addWidget(bb)
        return bb


# --------------------------------------------------------------------------
class ItemDialog(BaseDialog):
    """Add or edit an income / bill."""

    def __init__(self, data: AppData, item: RecurringItem | None = None, kind: str = BILL, parent=None):
        editing = item is not None
        kind = item.kind if item else kind
        super().__init__("Edit entry" if editing else ("Add income" if kind == INCOME else "Add bill"),
                         "Set it once — Balance Tracker works out every future date for you.", parent)
        self.item = item
        self.setMinimumWidth(500)

        # type toggle
        self.btn_income = QPushButton("Income")
        self.btn_bill = QPushButton("Bill / expense")
        group = QButtonGroup(self)
        for b in (self.btn_income, self.btn_bill):
            b.setObjectName("Chip")
            b.setCheckable(True)
            group.addButton(b)
        (self.btn_income if kind == INCOME else self.btn_bill).setChecked(True)

        self.name = QLineEdit(item.name if item else "")
        self.name.setPlaceholderText("e.g. Paycheque, Rent, Netflix")
        self.amount = MoneySpin()
        if item:
            self.amount.set_cents(item.amount)
        self.freq = QComboBox()
        for k, v in FREQUENCIES.items():
            self.freq.addItem(v, k)
        self.freq.setCurrentIndex(list(FREQUENCIES).index(item.frequency if item else "monthly"))
        self.start = date_edit(item.start_date if item else date.today())
        self.second = QSpinBox()
        self.second.setRange(1, 31)
        self.second.setValue(item.second_day if item else LAST_DAY)
        self.second.setSpecialValueText("")
        self.second_hint = label("31 = last day of the month", "Hint")
        self.has_end = QCheckBox("Stops on")
        self.end = date_edit((item.end_date if item and item.end_date else date.today() + timedelta(days=365)))
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

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        form.addRow("Type", hbox(self.btn_income, self.btn_bill, None))
        form.addRow("Name", self.name)
        form.addRow("Amount", hbox(self.amount, None))
        form.addRow("How often", self.freq)
        self.start_label = QLabel("Date")
        form.addRow(self.start_label, hbox(self.start, None))
        self.second_row_label = QLabel("Second day")
        form.addRow(self.second_row_label, hbox(self.second, self.second_hint, None))
        form.addRow("", hbox(self.has_end, self.end, None))
        form.addRow("On weekends", self.weekend)
        form.addRow("Category", self.category)
        form.addRow("Notes", self.notes)
        form.addRow("", self.active)
        self.outer.addLayout(form)

        self.preview = label("", "Hint", wrap=True)
        self.outer.addWidget(self.preview)
        self.add_buttons("Save" if editing else "Add")

        for sig in (self.freq.currentIndexChanged, self.start.dateChanged, self.second.valueChanged,
                    self.has_end.toggled, self.end.dateChanged, self.weekend.currentIndexChanged):
            sig.connect(self._refresh)
        self._refresh()
        self.name.setFocus()

    def _build(self) -> RecurringItem:
        it = RecurringItem(
            name=self.name.text().strip(),
            amount=self.amount.cents(),
            kind=INCOME if self.btn_income.isChecked() else BILL,
            frequency=self.freq.currentData(),
            start_date=from_qdate(self.start.date()),
            end_date=from_qdate(self.end.date()) if self.has_end.isChecked() else None,
            second_day=self.second.value(),
            weekend_rule=self.weekend.currentData(),
            category=self.category.currentText().strip(),
            notes=self.notes.toPlainText().strip(),
            active=self.active.isChecked(),
        )
        if self.item:
            it.id = self.item.id
            it.overrides = dict(self.item.overrides)
        return it

    def _refresh(self):
        f = self.freq.currentData()
        once = f == "once"
        self.start_label.setText("Date" if once else "First / next date")
        semi = f == "semimonthly"
        for w in (self.second, self.second_hint, self.second_row_label):
            w.setVisible(semi)
        self.has_end.setVisible(not once)
        self.end.setVisible(not once and self.has_end.isChecked())
        it = self._build()
        today = date.today()
        upcoming = []
        for sd in scheduled_dates(it, today + timedelta(days=800), since=today):
            post = shift_weekend(sd, it.weekend_rule)
            if post >= today:
                upcoming.append(post.strftime("%a %b %d"))
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
        if self.has_end.isChecked() and from_qdate(self.end.date()) < from_qdate(self.start.date()):
            QMessageBox.warning(self, "Check the dates", "The end date is before the start date.")
            return
        self.result_item = self._build()
        super().accept()


# --------------------------------------------------------------------------
class CheckInDialog(BaseDialog):
    """Enter the real bank balance; the gap vs. the plan becomes unplanned spending."""

    def __init__(self, data: AppData, today: date | None = None, parent=None):
        super().__init__("Balance check-in",
                         "What does your bank show right now? Any difference from the plan is "
                         "logged as unplanned spending (or income) and the forecast is re-anchored.",
                         parent)
        self.data = data
        self.setMinimumWidth(560)
        today = today or date.today()

        self.when = date_edit(today)
        if data.start:
            self.when.setMinimumDate(to_qdate(min(data.start.date, today)))
        self.when.setMaximumDate(to_qdate(today))
        self.balance = MoneySpin(allow_negative=True)
        self.includes = QCheckBox("This balance already includes that day's scheduled items")
        self.includes.setChecked(True)
        self.items_label = label("", "Hint", wrap=True)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Optional note — e.g. groceries, gas, birthday gift")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        form.addRow("Date", hbox(self.when, None))
        form.addRow("Actual balance", hbox(self.balance, None))
        form.addRow("", self.includes)
        form.addRow("", self.items_label)
        form.addRow("Note", self.note)
        self.outer.addLayout(form)

        box = QFrame()
        box.setObjectName("Card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(16, 14, 16, 14)
        self.projected_lbl = label("", "Muted")
        self.diff_lbl = label("", "StatValue")
        self.diff_sub = label("", "Hint", wrap=True)
        for w in (self.projected_lbl, self.diff_lbl, self.diff_sub):
            bl.addWidget(w)
        self.outer.addWidget(box)
        self.add_buttons("Save check-in")

        self.when.dateChanged.connect(self._refresh)
        self.balance.valueChanged.connect(self._refresh)
        self.includes.toggled.connect(self._refresh)
        self._refresh(initial=True)
        self.balance.setFocus()

    def _projected(self):
        d = from_qdate(self.when.date())
        # Project without any check-in already saved for this day, so editing works.
        temp = AppData(items=self.data.items,
                       checkpoints=[c for c in self.data.checkpoints if c.date != d],
                       settings=self.data.settings)
        f = Forecast(temp, d)
        todays = [o for i in self.data.items for o in occurrences(i, d, d)]
        before = f.balance_before(d)
        after = f.balance_on(d)
        return d, before, after, todays

    def _refresh(self, *_, initial: bool = False):
        d, before, after, todays = self._projected()
        self.includes.setVisible(bool(todays))
        if todays:
            self.items_label.setText("Scheduled that day: " + ", ".join(
                f"{o.item.name} {money.fmt(o.amount, signed=True)}" for o in todays))
        self.items_label.setVisible(bool(todays))
        projected = after if (self.includes.isChecked() or not todays) else before
        if initial and projected is not None:
            self.balance.set_cents(projected)
        if projected is None:
            self.projected_lbl.setText("This replaces your starting balance."
                                       if self.data.start and d == self.data.start.date
                                       else "No projection for this date.")
            self.diff_lbl.setText("")
            self.diff_sub.setText("")
            self._proj = None
            return
        self._proj = projected
        diff = self.balance.cents() - projected
        self.projected_lbl.setText(f"The plan expected {money.fmt(projected)}")
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
        d, *_ = self._projected()
        self.result_checkpoint = Checkpoint(
            date=d, balance=self.balance.cents(),
            includes_today=self.includes.isChecked(), note=self.note.text().strip())
        super().accept()


# --------------------------------------------------------------------------
class WelcomeDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("Welcome to Balance Tracker 👋",
                         "Let's start with what's in your chequing account today. You'll add your "
                         "paycheques and bills next, and Balance Tracker will forecast every day ahead.",
                         parent)
        self.setMinimumWidth(480)
        self.account = QLineEdit("Chequing")
        self.balance = MoneySpin(allow_negative=True)
        self.when = date_edit(date.today())
        self.includes = QCheckBox("Anything scheduled today has already landed")
        self.includes.setChecked(True)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        form.addRow("Account name", self.account)
        form.addRow("Current balance", hbox(self.balance, None))
        form.addRow("As of", hbox(self.when, None))
        form.addRow("", self.includes)
        self.outer.addLayout(form)
        self.outer.addWidget(label("Tip: already have a backup? Cancel this and use "
                                   "Settings → Import backup.", "Hint", wrap=True))
        self.add_buttons("Get started")
        self.balance.setFocus()

    def accept(self):
        self.result_checkpoint = Checkpoint(date=from_qdate(self.when.date()), balance=self.balance.cents(),
                                            includes_today=self.includes.isChecked(), note="Starting balance")
        self.result_account = self.account.text().strip() or "Chequing"
        super().accept()
