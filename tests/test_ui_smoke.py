"""Drives the real UI offscreen to make sure the main flows don't crash."""
import os
from datetime import date, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from balance_tracker import storage  # noqa: E402
from balance_tracker.models import AppData, BILL, INCOME, Checkpoint  # noqa: E402
from balance_tracker.ui import dialogs, theme  # noqa: E402
from balance_tracker.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_full_flow(app, tmp_path, monkeypatch):
    store = storage.Store(tmp_path)
    data = AppData()
    theme.apply_theme(app, "light")
    w = MainWindow(store, data)
    w.show()
    today = w.today

    # first run: welcome dialog
    def welcome_exec(self):
        self.balance.set_cents(150000)
        self.accept()
        return True
    monkeypatch.setattr(dialogs.WelcomeDialog, "exec", welcome_exec)
    w.startup_prompt()
    assert data.start.balance == 150000

    # add income + bill through the real dialog
    def item_exec(self):
        self.name.setText("Pay" if self.btn_income.isChecked() else "Rent")
        self.amount.set_cents(200000 if self.btn_income.isChecked() else 120000)
        self.freq.setCurrentIndex(list(self.freq.itemData(i) for i in range(self.freq.count())).index("biweekly"))
        self.start.setDate(dialogs.to_qdate(today + timedelta(days=3)))
        self.accept()
        return True
    monkeypatch.setattr(dialogs.ItemDialog, "exec", item_exec)
    w.add_item(INCOME)
    w.add_item(BILL)
    assert [i.kind for i in w.data.items] == [INCOME, BILL]
    assert w.forecast.balance_on(today + timedelta(days=3)) == 150000 + 200000 - 120000

    # skip one occurrence, then undo
    pay = w.data.items[0]
    key = (today + timedelta(days=3)).isoformat()
    w.set_override(pay, key, None)
    assert w.forecast.balance_on(today + timedelta(days=3)) == 30000
    w.undo()
    assert w.forecast.balance_on(today + timedelta(days=3)) == 230000

    # every page refreshes in both ledger modes
    w.pages[1].every_day.setChecked(False)
    w.pages[1].every_day.setChecked(True)
    w.show_day(today + timedelta(days=200))
    for i in range(6):
        w.go(i)
        app.processEvents()

    # export / import round trip
    out = tmp_path / "b.json"
    storage.export_backup(w.data, out)
    assert storage.read_backup(out).items[0].name == "Pay"

    # settings -> dark theme
    sp = w.pages[5]
    sp.theme.setCurrentIndex(2)
    assert w.data.settings.theme == "dark"
    assert store.load().settings.theme == "dark"
    w.toggle_theme()
    assert w.data.settings.theme == "light" and not theme.is_dark()
    w.toggle_theme()
    assert theme.is_dark()


def test_checkin_dialog_math(app):
    d = AppData()
    t = date.today()
    d.checkpoints.append(Checkpoint(t - timedelta(days=5), 100000))
    dlg = dialogs.CheckInDialog(d, t)
    assert dlg._proj == 100000
    dlg.balance.set_cents(90000)
    dlg.accept()
    assert dlg.result_checkpoint.balance == 90000


def test_debts_and_afford(app, tmp_path, monkeypatch):
    from balance_tracker.models import Debt, RecurringItem
    t = date.today()
    data = AppData()
    data.checkpoints.append(Checkpoint(t, 300000))
    data.items.append(RecurringItem("Pay", 250000, INCOME, "biweekly", t + timedelta(days=2)))
    data.items.append(RecurringItem("Rent", 150000, BILL, "monthly", t + timedelta(days=5)))
    w = MainWindow(storage.Store(tmp_path), data)

    def debt_exec(self):
        self.name.setText("Visa")
        self.balance.set_cents(250000)
        self.apr.setValue(19.99)
        self.accept()
        return True
    monkeypatch.setattr(dialogs.DebtDialog, "exec", debt_exec)
    w.add_debt()
    assert w.plan is not None and w.plan.debt_free is not None
    page = w.pages[3]
    page.in_forecast.setChecked(True)
    assert any("Visa" in e.description for e in w.forecast.entries)
    assert w.forecast.lowest(t, t + timedelta(days=365))[1] >= data.settings.low_balance_threshold
    page.mode.setCurrentIndex(1)
    page.fixed.set_cents(10000)
    page.save_plan()
    assert w.data.settings.debt_mode == "fixed"
    w.go(3)
    app.processEvents()

    dlg = dialogs.AffordDialog(w.data, w.build_forecast, t, w)
    dlg.amount.set_cents(10_000_000)
    assert "Not" in dlg.verdict.text()
    dlg.amount.set_cents(100)
    assert "Yes" in dlg.verdict.text()


def test_date_field_popup(app):
    from PySide6.QtCore import QDate
    from balance_tracker.ui.widgets import DateField
    f = DateField(QDate(2026, 10, 1))
    seen = []
    f.dateChanged.connect(seen.append)
    f.open_calendar()
    f._popup._pick(QDate(2026, 10, 15))
    assert f.date() == QDate(2026, 10, 15) and seen and not f._popup.isVisible()
    f.setMinimumDate(QDate(2026, 11, 1))
    assert f.date() == QDate(2026, 11, 1)


def test_card_todo_and_reminders(app, tmp_path, monkeypatch):
    from balance_tracker.models import Debt, RecurringItem
    t = date.today()
    data = AppData()
    data.checkpoints.append(Checkpoint(t - timedelta(days=3), 300000))
    visa = Debt("Visa", 50000, 20.0)
    data.debts.append(visa)
    data.items.append(RecurringItem("Netflix", 1899, BILL, "monthly", t - timedelta(days=1), paid_with=visa.id))
    w = MainWindow(storage.Store(tmp_path), data)
    dash = w.pages[0]
    assert not dash.card_box.isHidden()
    key = f"{data.items[0].id}|{(t - timedelta(days=1)).isoformat()}"
    w.mark_card_paid(key)
    assert key in w.data.card_paid and dash.card_box.isHidden()

    out = tmp_path / "r.ics"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    dlg = dialogs.RemindersDialog(w.data, w.plan, t, w)
    assert dlg.card.isChecked()
    dlg.accept()
    assert "Pay Visa" in out.read_text(encoding="utf-8")

    # the item dialog offers the card under "Paid with"
    idlg = dialogs.ItemDialog(w.data, w.data.items[0], parent=w)
    assert idlg.paid_with.currentData() == visa.id
