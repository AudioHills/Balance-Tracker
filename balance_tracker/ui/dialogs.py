"""Dialogs: add/edit income or bill, balance check-in, first-run welcome."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from .. import money
from ..forecast import Forecast, occurrences, shift_weekend, scheduled_dates
from ..models import (
    AppData, BILL, Checkpoint, FREQUENCIES, INCOME, LAST_DAY, RecurringItem, WEEKEND_RULES,
)
from . import theme
from .widgets import DateField, MoneySpin, hbox, label


def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def from_qdate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def date_edit(d: date) -> DateField:
    return DateField(to_qdate(d))


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

    def __init__(self, data: AppData, today: date | None = None, parent=None, builder=None):
        self.builder = builder
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
        f = self.builder(data=temp, end=d) if self.builder else Forecast(temp, d)
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


# --------------------------------------------------------------------------
class DebtDialog(BaseDialog):
    """Add or edit a credit card, line of credit or loan."""

    PRESETS = {  # kind -> (min $, min %, plus interest)
        "credit_card": (1000, 1.0, True),
        "line_of_credit": (0, 0.0, True),
        "loan": (0, 0.0, False),
    }

    def __init__(self, data: AppData, debt=None, parent=None):
        from ..models import DEBT_KINDS
        super().__init__("Edit debt" if debt else "Add a debt",
                         "Enter what you owe today and the interest rate from your latest statement.", parent)
        self.data = data
        self.debt = debt
        self.setMinimumWidth(540)

        self.kind = QComboBox()
        for k, v in DEBT_KINDS.items():
            self.kind.addItem(v, k)
        self.name = QLineEdit(debt.name if debt else "")
        self.name.setPlaceholderText("e.g. Visa, TD Line of Credit, Car loan")
        self.balance = MoneySpin()
        self.apr = QDoubleSpinBox()
        self.apr.setRange(0, 99.99)
        self.apr.setDecimals(2)
        self.apr.setSuffix(" %")
        self.apr.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.apr.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.apr.setMinimumWidth(110)
        self.limit = MoneySpin()
        self.due = QSpinBox()
        self.due.setRange(1, 31)
        self.min_amount = MoneySpin()
        self.min_amount.setMinimumWidth(120)
        self.min_pct = QDoubleSpinBox()
        self.min_pct.setRange(0, 100)
        self.min_pct.setDecimals(2)
        self.min_pct.setSuffix(" %")
        self.min_pct.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.min_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.plus_int = QCheckBox("plus that month's interest")
        self.linked = QComboBox()
        self.linked.addItem("None — the plan will schedule the payments", "")
        for it in data.items:
            if it.kind == BILL:
                self.linked.addItem(f"{it.name} ({money.fmt(it.amount)} {FREQUENCIES[it.frequency].lower()})", it.id)
        self.notes = QLineEdit(debt.notes if debt else "")

        if debt:
            self.kind.setCurrentIndex(list(DEBT_KINDS).index(debt.kind))
            self.balance.set_cents(debt.balance)
            self.apr.setValue(debt.apr)
            self.limit.set_cents(debt.credit_limit)
            self.due.setValue(debt.due_day)
            self.min_amount.set_cents(debt.min_amount)
            self.min_pct.setValue(debt.min_percent)
            self.plus_int.setChecked(debt.min_plus_interest)
            i = self.linked.findData(debt.linked_bill_id)
            self.linked.setCurrentIndex(max(0, i))
        else:
            self.due.setValue(date.today().day)
            self._preset()
        self.kind.currentIndexChanged.connect(lambda: (not self.debt) and self._preset())

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)
        form.addRow("Type", self.kind)
        form.addRow("Name", self.name)
        form.addRow("Balance owed", hbox(self.balance, None))
        form.addRow("Interest rate", hbox(self.apr, label("yearly (APR)", "Hint"), None))
        self.limit_label = QLabel("Credit limit")
        form.addRow(self.limit_label, hbox(self.limit, label("optional", "Hint"), None))
        form.addRow("Payment due day", hbox(self.due, label("of each month (31 = last day)", "Hint"), None))
        form.addRow("Minimum payment", hbox(self.min_amount, label("or", "Muted"), self.min_pct,
                                             label("of the balance", "Muted"), None, spacing=8))
        form.addRow("", self.plus_int)
        form.addRow("Already a bill?", self.linked)
        form.addRow("Notes", self.notes)
        self.outer.addLayout(form)
        self.outer.addWidget(label("“Already a bill?” — if you added this payment under Income & Bills, "
                                   "pick it so it isn't counted twice; the plan's payments replace it.",
                                   "Hint", wrap=True))
        self.info = label("", "Hint", wrap=True)
        self.outer.addWidget(self.info)
        self.add_buttons("Save" if debt else "Add debt")
        for sig in (self.balance.valueChanged, self.apr.valueChanged, self.min_amount.valueChanged,
                    self.min_pct.valueChanged, self.plus_int.toggled, self.kind.currentIndexChanged):
            sig.connect(self._refresh)
        self._refresh()
        self.name.setFocus()

    def _preset(self):
        amt, pct, plus = self.PRESETS[self.kind.currentData()]
        self.min_amount.set_cents(amt)
        self.min_pct.setValue(pct)
        self.plus_int.setChecked(plus)

    def _build(self):
        from ..models import Debt
        d = Debt(name=self.name.text().strip(), balance=self.balance.cents(), apr=self.apr.value(),
                 kind=self.kind.currentData(), due_day=self.due.value(), min_amount=self.min_amount.cents(),
                 min_percent=self.min_pct.value(), min_plus_interest=self.plus_int.isChecked(),
                 credit_limit=self.limit.cents(), linked_bill_id=self.linked.currentData() or "",
                 notes=self.notes.text().strip())
        if self.debt:
            d.id = self.debt.id
            d.updated_on = date.today() if d.balance != self.debt.balance else self.debt.updated_on
        return d

    def _refresh(self):
        from ..debts import minimum_payment
        is_loan = self.kind.currentData() == "loan"
        self.limit.setVisible(not is_loan)
        self.limit_label.setVisible(not is_loan)
        d = self._build()
        interest = d.balance * d.apr / 1200
        mp = minimum_payment(d, d.balance + interest, interest)
        col = theme.colors()
        text = (f"Interest this month ≈ {money.fmt(round(interest))} · minimum payment ≈ "
                f"{money.fmt(round(mp))}")
        if d.balance and mp <= interest + 0.5:
            text += "  —  ⚠ the minimum only covers interest, so this balance would never go down."
            self.info.setStyleSheet(f"color: {col['warning']};")
        else:
            self.info.setStyleSheet("")
        self.info.setText(text)

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing name", "Please give this debt a name.")
            return
        self.result_debt = self._build()
        super().accept()


# --------------------------------------------------------------------------
class AffordDialog(BaseDialog):
    """'Can I afford it?' — test a one-time purchase against the forecast."""

    def __init__(self, data: AppData, builder, today: date, parent=None):
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
        self.when = date_edit(today)
        self.when.setMinimumDate(to_qdate(today))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        form.addRow("Purchase", self.name)
        form.addRow("Amount", hbox(self.amount, None))
        form.addRow("On", hbox(self.when, None))
        self.outer.addLayout(form)

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
        self._refresh()
        self.amount.setFocus()

    def _refresh(self):
        from ..forecast import horizon_end
        cents = self.amount.cents()
        d = from_qdate(self.when.date())
        cushion = self.data.settings.low_balance_threshold
        end = horizon_end(self.data, self.today)
        item = RecurringItem(name="test", amount=cents, kind=BILL, frequency="once", start_date=d, id="")
        from ..forecast import Occurrence
        f = self.builder(extra=[Occurrence(d, d, -cents, item)])
        low = f.lowest(d, end)
        col = theme.colors()
        if low is None:
            self.verdict.setText("Add a starting balance first")
            return
        safe = (self.builder().lowest(d, end) or (d, 0))[1] - cushion
        if cents == 0:
            self.verdict.setText(f"You can spend up to {money.fmt(max(0, safe))}")
            self.verdict.setStyleSheet(f"color: {col['accent']};")
            self.detail.setText(f"on {d.strftime('%b %d')} and still keep your {money.fmt(cushion)} cushion "
                                f"through {end.strftime('%B %Y')}.")
            self.tip.setText("")
            return
        if low[1] >= cushion:
            self.verdict.setText("Yes — you can afford it ✓")
            self.verdict.setStyleSheet(f"color: {col['positive']};")
            self.detail.setText(f"Your lowest balance afterwards would be {money.fmt(low[1])} on "
                                f"{low[0].strftime('%b %d')}, still above your {money.fmt(cushion)} cushion.")
            self.tip.setText("Your debt plan's extra payments will shrink a little to make room for it."
                             if self.plan_note else "")
        elif low[1] >= 0:
            self.verdict.setText("Tight — it dips into your cushion")
            self.verdict.setStyleSheet(f"color: {col['warning']};")
            self.detail.setText(f"Your balance would fall to {money.fmt(low[1])} on {low[0].strftime('%b %d')}.")
            self.tip.setText(self._later_tip(cents, d, cushion, end))
        else:
            self.verdict.setText("Not right now ✕")
            self.verdict.setStyleSheet(f"color: {col['negative']};")
            self.detail.setText(f"You'd be overdrawn by {money.fmt(-low[1])} on {low[0].strftime('%b %d')}.")
            self.tip.setText(self._later_tip(cents, d, cushion, end))

    def _later_tip(self, cents, d, cushion, end):
        """Find the first later date this purchase would fit."""
        from ..forecast import Occurrence
        base = self.builder()
        day = d + timedelta(days=1)
        while day <= end:
            low = base.lowest(day, end)
            if low and low[1] - cents >= cushion:
                item = RecurringItem(name="t", amount=cents, kind=BILL, frequency="once", start_date=day, id="")
                f = self.builder(extra=[Occurrence(day, day, -cents, item)])
                if f.lowest(day, end)[1] >= cushion:
                    return f"💡 It would fit if you wait until {day.strftime('%A, %B %d')}."
            day += timedelta(days=1)
        return "💡 It doesn't fit within your forecast window without dipping below your cushion."

    def accept(self):
        if self.amount.cents() <= 0:
            QMessageBox.information(self, "Enter an amount", "Enter the purchase amount first.")
            return
        self.result_item = RecurringItem(
            name=self.name.text().strip() or "Planned purchase", amount=self.amount.cents(), kind=BILL,
            frequency="once", start_date=from_qdate(self.when.date()), category="Planned purchase")
        super().accept()
