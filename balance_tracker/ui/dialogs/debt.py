"""Add/edit a credit card, line of credit or loan."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QMessageBox, QSpinBox

from ... import money
from ...debts import minimum_payment
from ...models import BILL, DEBT_KINDS, FREQUENCIES, AppData, Debt
from .. import theme
from ..widgets import MoneySpin, hbox, label
from .base import BaseDialog, form


def _percent_box(maximum: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0, maximum)
    box.setDecimals(2)
    box.setSuffix(" %")
    box.setButtonSymbols(QDoubleSpinBox.NoButtons)
    box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return box


class DebtDialog(BaseDialog):
    """On accept, the new version of the debt is in `result_debt`."""

    PRESETS = {  # kind -> (minimum $, minimum % of balance, plus that month's interest)
        "credit_card": (1000, 1.0, True),
        "line_of_credit": (0, 0.0, True),
        "loan": (0, 0.0, False),
    }

    def __init__(self, data: AppData, debt: Debt | None = None, parent=None, today: date | None = None):
        super().__init__("Edit debt" if debt else "Add a debt",
                         "Enter what you owe today and the interest rate from your latest statement.", parent)
        self.data = data
        self.debt = debt
        self.today = today or date.today()
        self.setMinimumWidth(540)

        self.kind = QComboBox()
        for k, v in DEBT_KINDS.items():
            self.kind.addItem(v, k)
        self.name = QLineEdit(debt.name if debt else "")
        self.name.setPlaceholderText("e.g. Visa, TD Line of Credit, Car loan")
        self.balance = MoneySpin()
        self.apr = _percent_box(99.99)
        self.apr.setMinimumWidth(110)
        self.limit = MoneySpin()
        self.due = QSpinBox()
        self.due.setRange(1, 31)
        self.min_amount = MoneySpin()
        self.min_amount.setMinimumWidth(120)
        self.min_pct = _percent_box(100)
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
            self.linked.setCurrentIndex(max(0, self.linked.findData(debt.linked_bill_id)))
        else:
            self.due.setValue(self.today.day)
            self._preset()
            self.kind.currentIndexChanged.connect(self._preset)

        f = form()
        f.addRow("Type", self.kind)
        f.addRow("Name", self.name)
        f.addRow("Balance owed", hbox(self.balance, None))
        f.addRow("Interest rate", hbox(self.apr, label("yearly (APR)", "Hint"), None))
        self.limit_label = QLabel("Credit limit")
        f.addRow(self.limit_label, hbox(self.limit, label("optional", "Hint"), None))
        f.addRow("Payment due day", hbox(self.due, label("of each month (31 = last day)", "Hint"), None))
        f.addRow("Minimum payment", hbox(self.min_amount, label("or", "Muted"), self.min_pct,
                                         label("of the balance", "Muted"), None, spacing=8))
        f.addRow("", self.plus_int)
        f.addRow("Already a bill?", self.linked)
        f.addRow("Notes", self.notes)
        self.outer.addLayout(f)
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

    def _build(self) -> Debt:
        d = Debt(name=self.name.text().strip(), balance=self.balance.cents(), apr=self.apr.value(),
                 kind=self.kind.currentData(), due_day=self.due.value(), min_amount=self.min_amount.cents(),
                 min_percent=self.min_pct.value(), min_plus_interest=self.plus_int.isChecked(),
                 credit_limit=self.limit.cents(), linked_bill_id=self.linked.currentData() or "",
                 notes=self.notes.text().strip(), updated_on=self.today)
        if self.debt:
            d.id = self.debt.id
            d.updated_on = self.today if d.balance != self.debt.balance else self.debt.updated_on
        return d

    def _refresh(self):
        is_loan = self.kind.currentData() == "loan"
        self.limit.setVisible(not is_loan)
        self.limit_label.setVisible(not is_loan)
        d = self._build()
        interest = d.balance * d.apr / 1200
        mp = minimum_payment(d, d.balance + interest, interest)
        text = f"Interest this month ≈ {money.fmt(round(interest))} · minimum payment ≈ {money.fmt(round(mp))}"
        if d.balance and mp <= interest + 0.5:
            text += "  —  ⚠ the minimum only covers interest, so this balance would never go down."
            self.info.setStyleSheet(f"color: {theme.colors()['warning']};")
        else:
            self.info.setStyleSheet("")
        self.info.setText(text)

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing name", "Please give this debt a name.")
            return
        self.result_debt = self._build()
        super().accept()
