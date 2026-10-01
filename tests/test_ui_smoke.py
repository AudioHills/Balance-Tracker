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
    for i in range(5):
        w.go(i)
        app.processEvents()

    # export / import round trip
    out = tmp_path / "b.json"
    storage.export_backup(w.data, out)
    assert storage.read_backup(out).items[0].name == "Pay"

    # settings -> dark theme
    sp = w.pages[4]
    sp.theme.setCurrentIndex(2)
    assert w.data.settings.theme == "dark"
    assert store.load().settings.theme == "dark"


def test_checkin_dialog_math(app):
    d = AppData()
    t = date.today()
    d.checkpoints.append(Checkpoint(t - timedelta(days=5), 100000))
    dlg = dialogs.CheckInDialog(d, t)
    assert dlg._proj == 100000
    dlg.balance.set_cents(90000)
    dlg.accept()
    assert dlg.result_checkpoint.balance == 90000
