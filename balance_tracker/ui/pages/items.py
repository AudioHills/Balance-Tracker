"""Income & Bills: the recurring entries the forecast is built from."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLineEdit, QMenu, QPushButton

from ... import money
from ...forecast import monthly_equivalent, next_occurrence
from ...formatting import nice_date, ordinal, plural
from ...insights import bills_by_category, monthly_totals
from ...models import BILL, FREQUENCIES, INCOME, LAST_DAY, RecurringItem
from ..charts import CategoryBars
from ..widgets import Card, StatCard, chips, chosen, hbox, label
from .common import Page, add_row, cell, row_data, table


def describe_frequency(item: RecurringItem) -> str:
    """"Monthly", or "Twice a month (15th & last day)"."""
    text = FREQUENCIES[item.frequency]
    if item.frequency == "semimonthly":
        second = "last day" if item.second_day >= LAST_DAY else ordinal(item.second_day)
        text += f" ({ordinal(item.start_date.day)} & {second})"
    return text


class ItemsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Income & Bills", "Everything that regularly moves money in or out of your account.")
        add_inc = QPushButton("+  Add income")
        add_inc.setToolTip("Ctrl+I")
        add_inc.clicked.connect(lambda: ctx.add_item(INCOME))
        add_bill = QPushButton("+  Add bill")
        add_bill.setObjectName("Primary")
        add_bill.setToolTip("Ctrl+B")
        add_bill.clicked.connect(lambda: ctx.add_item(BILL))
        self.header.addLayout(hbox(add_inc, add_bill))

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_inc = StatCard("INCOME / MONTH")
        self.c_bill = StatCard("BILLS / MONTH")
        self.c_net = StatCard("LEFT OVER / MONTH")
        for i, w in enumerate((self.c_inc, self.c_bill, self.c_net)):
            grid.addWidget(w, 0, i)
        self.body.addLayout(grid)

        self.categories = Card()
        self.categories.lay.addLayout(hbox(label("Where your bills go", "SectionTitle"), None,
                                           label("Average per month, by category", "Hint")))
        self.cat_bars = CategoryBars()
        self.categories.lay.addWidget(self.cat_bars)
        self.cat_hint = label("", "Hint", wrap=True)
        self.categories.lay.addWidget(self.cat_hint)
        self.body.addWidget(self.categories)

        self.filter_btns = chips([("All", None), ("Income", INCOME), ("Bills", BILL)], self.refresh, self.widget)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.refresh)
        self.body.addLayout(hbox(*self.filter_btns, None, self.search, spacing=6))

        self.table = table(["Name", "Category", "Amount", "How often", "Next", "≈ per month", "Status"], 0)
        self.table.setMinimumHeight(420)
        self.table.cellDoubleClicked.connect(lambda r, _: self._edit_row(r))
        self.table.customContextMenuRequested.connect(self.menu)
        self.body.addWidget(self.table, 1)
        self.body.addWidget(label("Double-click to edit · right-click for more options", "Hint"))

    def focus_search(self) -> bool:
        self.search.setFocus()
        self.search.selectAll()
        return True

    def _edit_row(self, r: int):
        item_id = row_data(self.table, r)
        if item_id:
            self.ctx.edit_item(item_id)

    def refresh(self):
        ctx, today = self.ctx, self.ctx.today
        items = ctx.data.items
        totals = monthly_totals(items, today)
        self.c_inc.set(money.fmt(totals.income), plural(sum(1 for i in items if i.kind == INCOME), "income entry",
                                                         "income entries"), "positive")
        self.c_bill.set(money.fmt(totals.bills), plural(sum(1 for i in items if i.kind == BILL), "bill"))
        self.c_net.set(money.fmt(totals.net, True), "before unplanned spending",
                       "positive" if totals.net >= 0 else "negative")

        shares = bills_by_category(items, today)
        self.categories.setVisible(len(shares) >= 2)
        self.cat_bars.set_data([(c.category, c.monthly, c.share) for c in shares])
        uncategorized = sum(1 for i in items if i.kind == BILL and not i.category.strip())
        self.cat_hint.setText(("1 bill has no category — edit it" if uncategorized == 1 else
                               f"{uncategorized} bills have no category — edit them")
                              + " to see the full picture." if uncategorized else "")

        kind = chosen(self.filter_btns)
        q = self.search.text().strip().lower()
        shown = [i for i in items if (kind is None or i.kind == kind)
                 and (not q or q in i.name.lower() or q in i.category.lower())]
        nexts = {i.id: next_occurrence(i, today) for i in shown}
        shown.sort(key=lambda i: (not i.active, i.kind != INCOME,
                                  nexts[i.id].date if nexts[i.id] else date.max, i.name.lower()))
        t = self.table
        t.setRowCount(0)
        for i in shown:
            nxt = nexts[i.id]
            status = "Paused" if not i.active else ("Finished" if nxt is None else "Active")
            dim = None if i.active and nxt else "muted"
            tone = dim or ("positive" if i.kind == INCOME else None)
            card = ctx.data.card_for(i)
            add_row(t,
                    cell(("▲  " if i.kind == INCOME else "▼  ") + i.name, bold=True, color=tone, data=i.id),
                    cell(" · ".join(x for x in (i.category, f"💳 on {card.name}" if card else "") if x),
                         color="muted"),
                    cell(money.fmt(i.signed_amount, True), Qt.AlignRight, tone),
                    cell(describe_frequency(i), color=dim),
                    cell(nice_date(nxt.date, today) if nxt else "—", color=dim),
                    cell(money.fmt(monthly_equivalent(i), True) if i.frequency != "once" else "one-time",
                         Qt.AlignRight, "muted"),
                    cell(status, color="positive" if status == "Active" else "muted"))
        if not shown:
            add_row(t, cell("Nothing here yet — add your paycheque and bills above." if not items
                            else "Nothing matches your search.", color="muted"))

    def menu(self, pos):
        item_id = row_data(self.table, self.table.rowAt(pos.y()))
        item = self.ctx.data.item(item_id) if item_id else None
        if item is None:
            return
        m = QMenu(self.table)
        m.addAction("Edit…", lambda: self.ctx.edit_item(item.id))
        m.addAction("Change amount from a date on…", lambda: self.ctx.change_amount_from(item.id))
        m.addAction("Duplicate…", lambda: self.ctx.duplicate_item(item.id))
        m.addAction("Resume" if not item.active else "Pause (exclude from forecast)",
                    lambda: self.ctx.toggle_item(item.id))
        m.addSeparator()
        m.addAction("Delete", lambda: self.ctx.delete_item(item.id))
        m.exec(self.table.viewport().mapToGlobal(pos))
