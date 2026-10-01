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
        self.paid_label = QLabel("Paid with")
        form.addRow(self.paid_label, self.paid_with)
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

        for sig in (self.btn_bill.toggled, self.freq.currentIndexChanged, self.start.dateChanged, self.second.valueChanged,
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
            paid_with=(self.paid_with.currentData() or "") if self.btn_bill.isChecked() else "",
        )
        if self.item:
            it.id = self.item.id
            it.overrides = dict(self.item.overrides)
        return it

    def _refresh(self):
        show_card = self.btn_bill.isChecked() and self.paid_with.count() > 1
        self.paid_with.setVisible(show_card)
        self.paid_label.setVisible(show_card)
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
            self.diff_lbl.setText("")
            self.diff_sub.setText("")
            self.after_lbl.setText("")
            self._proj = None
            return
        self._proj = projected
        diff = self.balance.cents() - projected
        self.projected_lbl.setText(f"The plan expected {money.fmt(projected)}")
        day_word = "Balance today" if d == date.today() else "That day"
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


# --------------------------------------------------------------------------
class RemindersDialog(BaseDialog):
    """Export reminders as a calendar file the phone can import."""

    def __init__(self, data: AppData, plan, today: date, parent=None):
        from PySide6.QtCore import QTime
        from PySide6.QtWidgets import QTimeEdit
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
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        form.addRow("Remind me at", hbox(self.time, None))
        form.addRow("Heads-up", hbox(self.before, label("for debt payments and bills", "Hint"), None))
        form.addRow("Cover the next", hbox(self.months, None))
        self.outer.addLayout(form)
        self.count = label("", "SectionTitle")
        self.outer.addWidget(self.count)
        self.outer.addWidget(self._howto(
            "<b>Getting it onto your phone</b><br>"
            "• <b>Google Calendar</b> (Android or iPhone): on a computer go to calendar.google.com → ⚙ Settings → "
            "Import &amp; export → choose the file. Tip: create a calendar called “Bills” first and import into it.<br>"
            "• <b>iPhone Calendar</b>: email the file to yourself, open the attachment on your iPhone → Add All.<br>"
            "• <b>Outlook</b>: double-click the file, or Calendar → Add calendar → Upload from file.<br>"
            "Re-export whenever your bills or plan change — events with the same ID are updated, not duplicated."))
        bb = self.add_buttons("Save calendar file…")
        for w in (self.card, self.debts, self.bills, self.paydays):
            w.toggled.connect(self._refresh)
        self.before.valueChanged.connect(self._refresh)
        self.months.valueChanged.connect(self._refresh)
        self._refresh()

    @staticmethod
    def _howto(html: str):
        lb = label(html, "Hint", wrap=True)
        lb.setMinimumHeight(lb.heightForWidth(572) + 8)
        return lb

    def _collect(self):
        from ..reminders import collect
        return collect(self.data, self.plan, self.today, self.months.value(), self.card.isChecked(),
                       self.debts.isChecked(), self.bills.isChecked(), self.paydays.isChecked(),
                       self.before.value())

    def _refresh(self):
        n = len(self._collect())
        self.count.setText(f"{n} reminder{'s' if n != 1 else ''} will be added")

    def accept(self):
        from PySide6.QtWidgets import QFileDialog
        from ..reminders import to_ics
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


# --------------------------------------------------------------------------
class NotifyDialog(BaseDialog):
    """Daily reminder emails and phone (ntfy) notifications."""

    def __init__(self, data: AppData, folder, parent=None):
        import secrets as _secrets
        from PySide6.QtCore import QTime
        from PySide6.QtWidgets import QApplication, QScrollArea, QTimeEdit, QWidget
        from .. import notify
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
        self.password.setPlaceholderText("Saved — leave blank to keep" if self.has_saved_pw else "16-character app password")
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
        self.topic = QLineEdit(s.ntfy_topic or f"balance-tracker-{_secrets.token_hex(5)}")
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.topic.text()))
        nf = QFormLayout()
        nf.setLabelAlignment(Qt.AlignRight)
        nf.setVerticalSpacing(8)
        nf.addRow("", self.ntfy_on)
        nf.addRow("Topic", hbox(self.topic, copy))
        nf.addRow("", label("Install <b>ntfy</b> from the Play Store or App Store → tap <b>+</b> → "
                            "<b>Subscribe to topic</b> → paste the topic above. Messages go through the public "
                            "ntfy.sh service; keep the topic name private (it works like a password).",
                            "Hint", wrap=True))

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
        test = bb.addButton("Send a test now", QDialogButtonBox.ActionRole)
        test.clicked.connect(self.send_test)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self._provider_changed(initial=True)
        self.resize(680, 760)

    def _provider_changed(self, *_, initial=False):
        from .. import notify
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
        if self.ntfy_on.isChecked() and len(self.topic.text().strip()) < 6:
            QMessageBox.warning(self, "Topic", "Pick a longer, hard-to-guess topic name.")
            return False
        return True

    def send_test(self):
        import copy
        from PySide6.QtGui import QGuiApplication, QCursor
        from .. import notify
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
        QGuiApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            errors = notify.deliver(trial, self.folder, digest)
        finally:
            QGuiApplication.restoreOverrideCursor()
        col = theme.colors()
        if errors:
            self.status.setStyleSheet(f"color: {col['negative']};")
            self.status.setText("Couldn't send: " + " · ".join(errors) +
                                "\nCheck the address and app password (not your normal password).")
        else:
            self.status.setStyleSheet(f"color: {col['positive']};")
            self.status.setText("✓ Test sent — check your inbox (and spam folder) or the ntfy app.")

    def accept(self):
        from .. import notify
        if not self._validate():
            return
        self._apply(self.data.settings)
        if self.password.text():
            notify.save_password(self.folder, self.password.text())
        self.want_task = self.background.isChecked() and (self.email_on.isChecked() or self.ntfy_on.isChecked())
        super().accept()
