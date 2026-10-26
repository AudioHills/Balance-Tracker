"""Drives the real UI offscreen to make sure the main flows don't crash."""
import os
from datetime import date, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6 import QtCore  # noqa: E402

from balance_tracker import storage  # noqa: E402
from balance_tracker.forecast import add_months  # noqa: E402
from balance_tracker.models import BILL, INCOME, AppData, Checkpoint  # noqa: E402
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
    from balance_tracker.models import RecurringItem
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


def test_iphone_sync_roundtrip(app, tmp_path):
    import json

    from balance_tracker import sync
    from balance_tracker.models import RecurringItem
    t = date.today()
    data = AppData()
    data.checkpoints.append(Checkpoint(t, 100000))
    data.items.append(RecurringItem("Rent", 150000, BILL, "monthly", t))
    store = storage.Store(tmp_path / "pc")
    w = MainWindow(store, data)
    folder = tmp_path / "iCloudDrive" / "Balance Tracker"
    w.enable_sync(str(folder))
    shared = folder / sync.SYNC_FILE
    assert shared.exists()

    # the phone edits the file (adds a bill) and saves a copy next to it
    phone = AppData.from_dict(json.loads(shared.read_text()))
    prev = AppData.from_dict(phone.to_dict())
    phone.items.append(RecurringItem("Gym", 5000, BILL, "monthly", t))
    sync.stamp(prev, phone, "2099-01-01T00:00:00.000Z")
    (folder / "BalanceTracker-sync 2.json").write_text(json.dumps(phone.to_dict()))

    assert w.sync_in(force=True) == 1
    assert {i.name for i in w.data.items} == {"Rent", "Gym"}
    gym = next(i for i in store.load().items if i.name == "Gym")
    assert gym.updated == "2099-01-01T00:00:00.000Z"  # kept the phone's timestamp
    assert not (folder / "BalanceTracker-sync 2.json").exists()  # tidied into backups
    assert "Gym" in shared.read_text()
    assert w.sync_in(force=True) == 0  # nothing new
    w.go(5)
    app.processEvents()


def test_hide_balance_eye(app, tmp_path):
    t = date.today()
    data = AppData()
    data.checkpoints.append(Checkpoint(t, 123456))
    store = storage.Store(tmp_path)
    w = MainWindow(store, data)
    dash = w.pages[0]
    assert dash.c_today.value.text() == "$1,234.56"
    dash.eye.click()
    assert dash.c_today.value.text() == "******" and w.side_balance.text() == "******"
    assert store.load().settings.hide_balance is True  # remembered
    w2 = MainWindow(store, store.load())  # reopening the app keeps it hidden
    assert w2.pages[0].c_today.value.text() == "******"
    w2.side_eye.click()
    assert w2.side_balance.text() == "$1,234.56"
    from balance_tracker.sync import sync_payload
    assert "hide_balance" not in sync_payload(store.load())  # a per-device choice, not synced


def test_checkin_explains_items_still_to_come(app, tmp_path):
    from balance_tracker.models import RecurringItem
    t = date.today()
    data = AppData()
    data.checkpoints.append(Checkpoint(t - timedelta(days=3), 141801))
    data.items.append(RecurringItem("Rent", 165000, BILL, "monthly", t))
    w = MainWindow(storage.Store(tmp_path), data)
    dlg = dialogs.CheckInDialog(w.data, t, w, builder=w.build_forecast)
    assert dlg.includes.text() == "Rent −$1,650.00 has already gone through"
    dlg.balance.set_cents(250000)
    assert "$2,500.00" in dlg.after_lbl.text()
    dlg.includes.setChecked(False)
    assert dlg.after_lbl.text() == "Balance today will show $850.00 once Rent comes out."
    dlg.accept()
    w.data.add_checkpoint(dlg.result_checkpoint)
    w.commit()
    assert w.pages[0].c_today.value.text() == "$850.00"
    assert "Bank showed $2,500.00 at check-in" in w.pages[0].c_today.sub.text()


# ---- 2.0 ---------------------------------------------------------------------
def sample_window(tmp_path, **settings):
    from balance_tracker.models import RecurringItem
    t = date.today()
    data = AppData()
    data.checkpoints.append(Checkpoint(t, 150000))
    data.items.append(RecurringItem("Pay", 200000, INCOME, "biweekly", t + timedelta(days=5)))
    data.items.append(RecurringItem("Rent", 120000, BILL, "monthly", t + timedelta(days=8), category="Housing"))
    data.items.append(RecurringItem("Phone", 6000, BILL, "monthly", t + timedelta(days=2), category="Utilities"))
    for k, v in settings.items():
        setattr(data.settings, k, v)
    return MainWindow(storage.Store(tmp_path), data), t


def test_amount_boxes_have_room_to_show_their_text(app, tmp_path):
    """The stylesheet once left every spin box's text field 1px wide, so amounts looked blank."""
    theme.apply_theme(app, "light")
    w, _ = sample_window(tmp_path)
    w.show()
    w.go(5)
    app.processEvents()
    boxes = [b for b in w.findChildren(QtWidgets.QAbstractSpinBox) if b.isVisible()]
    assert boxes and all(b.lineEdit().width() > b.width() - 30 for b in boxes)


def test_payday_card_and_category_breakdown(app, tmp_path):
    w, t = sample_window(tmp_path)
    dash = w.pages[0]
    assert not dash.payday_box.isHidden() and "Until payday" in dash.payday_title.text()
    assert dash.m_bills.value.text() == "$60.00" and "/ day" in dash.m_daily.value.text()
    w.go(2)
    items = w.pages[2]
    assert not items.categories.isHidden()
    assert [r[0] for r in items.cat_bars.rows] == ["Housing", "Utilities"]


def test_card_rows_are_replaced_not_stacked(app, tmp_path):
    """Old rows must disappear at once when the card list is rebuilt, not linger until deleted."""
    from balance_tracker.models import Debt, RecurringItem
    t = date.today()
    data = AppData()
    data.checkpoints.append(Checkpoint(t - timedelta(days=3), 300000))
    visa = Debt("Visa", 50000, 20.0)
    data.debts.append(visa)
    data.items.append(RecurringItem("Netflix", 1899, BILL, "monthly", t - timedelta(days=1), paid_with=visa.id))
    w = MainWindow(storage.Store(tmp_path), data)
    w.show()
    for _ in range(3):
        w.refresh_all()
    app.processEvents()  # shows the new rows; deferred deletes of the old ones are still pending
    labels = w.pages[0].card_box.findChildren(QtWidgets.QLabel)
    assert len([lb for lb in labels if lb.isVisible() and "Netflix" in lb.text()]) == 1


def test_change_amount_from_a_date(app, tmp_path, monkeypatch):
    w, t = sample_window(tmp_path)
    rent = w.data.items[1]
    when = add_months(rent.start_date, 1)  # the second rent payment and later

    def exec_(self):
        self.amount.set_cents(130000)
        self.when.setDate(when)
        self.accept()
        return True
    monkeypatch.setattr(dialogs.ChangeAmountDialog, "exec", exec_)
    w.change_amount_from(rent.id)
    rents = [e for e in w.forecast.entries if e.description == "Rent"]
    assert [e.amount for e in rents[:3]] == [-120000, -130000, -130000]
    assert len([i for i in w.data.items if i.name == "Rent"]) == 2
    w.undo()
    assert [i.amount for i in w.data.items if i.name == "Rent"] == [120000]


def test_ledger_search(app, tmp_path):
    w, t = sample_window(tmp_path)
    w.go(1)
    page = w.pages[1]
    page.search.setText("hous")  # matches the Housing category
    shown = {page.table.item(r, 1).text() for r in range(page.table.rowCount())}
    assert shown == {"Rent"} and page.summary.text().startswith("Matching")
    page.search.clear()
    assert page.table.rowCount() > 10  # every day again


def test_undo_stack_and_sync_clears_it(app, tmp_path):
    w, _ = sample_window(tmp_path)
    w.delete_item(w.data.items[2].id)
    w.delete_item(w.data.items[1].id)
    assert len(w.data.items) == 1
    w.undo()
    w.undo()
    assert [i.name for i in w.data.items] == ["Pay", "Rent", "Phone"]
    w.undo()  # nothing left: says so instead of failing
    assert w.toast_w.text.text() == "Nothing to undo"


def test_duplicate_is_only_added_when_saved(app, tmp_path, monkeypatch):
    w, _ = sample_window(tmp_path)
    monkeypatch.setattr(dialogs.ItemDialog, "exec", lambda self: False)
    w.duplicate_item(w.data.items[1].id)
    assert len(w.data.items) == 3
    monkeypatch.setattr(dialogs.ItemDialog, "exec", lambda self: self.accept() or True)
    w.duplicate_item(w.data.items[1].id)
    copy = w.data.items[-1]
    assert copy.name == "Rent (copy)" and copy.id != w.data.items[1].id


def test_settings_only_save_what_changed(app, tmp_path):
    w, _ = sample_window(tmp_path)
    page = w.pages[5]
    w.data.settings.low_balance_threshold = 77700  # e.g. just synced from the phone; the page hasn't redrawn
    page.theme.setCurrentIndex(2)
    assert w.data.settings.theme == "dark" and w.data.settings.low_balance_threshold == 77700
    theme.apply_theme(app, "light")


def test_check_for_updates(app, tmp_path, monkeypatch):
    from balance_tracker import updates
    from balance_tracker.ui.pages import settings as settings_page
    monkeypatch.setattr(settings_page, "run_in_background", lambda parent, work, done: done(*_call(work)))
    w, _ = sample_window(tmp_path)
    page = w.pages[5]
    monkeypatch.setattr(updates, "latest_release", lambda: updates.Release("99.0.0", "https://example.com"))
    page.check_updates()
    assert "99.0.0 is available" in page.update_status.text()
    monkeypatch.setattr(updates, "latest_release", lambda: updates.Release("0.1", "https://example.com"))
    page.check_updates()
    assert "up to date" in page.update_status.text()

    def offline():
        raise OSError("no network")
    monkeypatch.setattr(updates, "latest_release", offline)
    page.check_updates()
    assert "Couldn't reach GitHub" in page.update_status.text() and page.update_btn.isEnabled()


def _call(work):
    try:
        return work(), None
    except Exception as e:  # noqa: BLE001
        return None, e


def test_shortcuts_are_bound_and_listed(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QKeySequence, QShortcut
    w, _ = sample_window(tmp_path)
    shown = []
    monkeypatch.setattr(dialogs.ShortcutsDialog, "exec", lambda self: shown.append(self) or 0)
    w.show_shortcuts()
    assert shown
    bound = {s.key().toString() for s in w.findChildren(QShortcut)}
    assert {QKeySequence(k).toString() for k, _, _ in w.shortcuts} <= bound
    w.focus_search()
    assert w.stack.currentIndex() == 1


def test_debt_before_a_starting_balance_does_not_crash(app, tmp_path):
    from balance_tracker.models import Debt
    data = AppData()
    data.debts.append(Debt("Visa", 100000, 19.99))
    w = MainWindow(storage.Store(tmp_path), data)
    w.go(3)
    assert w.pages[3].c_free.value.text() == "—"


def test_spending_room_is_measured_before_plan_extras(app, tmp_path):
    from balance_tracker.models import Debt
    w, t = sample_window(tmp_path, debt_in_forecast=True, low_balance_threshold=10000)
    w.data.debts.append(Debt("Visa", 500000, 19.99, due_day=28))
    w.commit()
    assert any(p.extra for p in w.plan.payments)
    dash = w.pages[0]
    assert dash.c_safe.value.text() != "$0.00" and "debt plan" in dash.c_safe.sub.text()
    assert dash.m_daily.value.text() != "$0.00 / day"


def test_restore_list_leaves_out_phone_sync_copies(app, tmp_path):
    w, _ = sample_window(tmp_path)
    w.commit()  # writes today's automatic backup
    (w.store.backup_dir / "merged-20260101-120000-BalanceTracker-sync 2.json").write_text("{}")
    w.go(5)
    labels = [w.pages[5].auto.itemText(i) for i in range(w.pages[5].auto.count())]
    assert any(t.startswith("Automatic backup") for t in labels)
    assert not any("iPhone" in t for t in labels)


def test_names_from_a_file_are_never_rendered_as_markup(app, tmp_path):
    from balance_tracker.models import Debt, RecurringItem
    w, t = sample_window(tmp_path)
    card = Debt("<a href='file:///C:/evil.exe'>Visa</a>", 0, 19.99, id="card")
    w.data.debts.append(card)
    w.data.items.append(RecurringItem("<h1>Netflix</h1>", 1599, BILL, "monthly", t, paid_with="card"))
    w.commit(toast="Added “<b>x</b>”")
    w.go(0)
    app.processEvents()
    assert w.toast_w.text.textFormat() == QtCore.Qt.PlainText
    shown = [lb for lb in w.pages[0].widget.findChildren(QtWidgets.QLabel) if "Netflix" in lb.text()]
    assert shown and all("&lt;h1&gt;" in lb.text() or lb.textFormat() == QtCore.Qt.PlainText for lb in shown)
    for lb in w.findChildren(QtWidgets.QLabel):
        if lb.textFormat() != QtCore.Qt.PlainText:
            assert "<h1>" not in lb.text() and "<a href='file" not in lb.text()


def test_app_lock_hides_everything_until_the_password(app, tmp_path, monkeypatch):
    from balance_tracker import applock
    w, _ = sample_window(tmp_path)
    w.show()
    w.lock_now()  # no password set yet: just a hint
    assert w.isVisible() and "Set a lock password" in w.toast_w.text.text()
    applock.set_password(tmp_path, "open sesame", idle_minutes=1)
    seen = {}

    def unlock_screen(screen):
        seen["hidden"] = not w.isVisible()
        screen.password.setText("wrong one")
        screen.try_unlock()
        seen["wrong"] = screen.message.text()
        screen.password.setText("open sesame")
        screen.try_unlock()
        return screen.result()

    monkeypatch.setattr(dialogs.LockScreen, "exec", unlock_screen)
    w.lock_now()
    assert seen == {"hidden": True, "wrong": "Wrong password"} and w.isVisible()
    # it locks by itself after the idle time
    w.lock_cfg = applock.load(tmp_path)
    monkeypatch.setattr("balance_tracker.ui.main_window.system_idle_seconds", lambda: 61.0)
    seen.clear()
    w._check_idle()
    assert seen.get("hidden") is True
    # Quit on the lock screen closes the app
    quits = []
    monkeypatch.setattr(dialogs.LockScreen, "exec", lambda screen: 0)
    monkeypatch.setattr(QtWidgets.QApplication, "quit", lambda: quits.append(1))
    w.lock_now()
    assert quits == [1]


def test_lock_setup_and_removal(app, tmp_path, monkeypatch):
    from balance_tracker import applock
    w, _ = sample_window(tmp_path)

    def setup(dlg):
        dlg.new.setText("open sesame")
        dlg.confirm.setText("open sesame")
        dlg.idle.setCurrentIndex(dlg.idle.findData(15))
        dlg.accept()
        return 1

    monkeypatch.setattr(dialogs.LockSetupDialog, "exec", setup)
    w.lock_settings()
    assert applock.load(tmp_path).idle_minutes == 15 and w.lock_cfg is not None
    w.go(5)
    assert "lock is on" in w.pages[5].lock_status.text()
    answers = iter(["nope", "open sesame"])
    monkeypatch.setattr("balance_tracker.ui.main_window.ask_password", lambda *a, **k: next(answers))
    w.remove_lock()
    assert applock.load(tmp_path) is None and w.lock_cfg is None


def test_encrypted_sync_from_the_pc(app, tmp_path, monkeypatch):
    import json

    from balance_tracker import sync
    from balance_tracker.ui import main_window
    monkeypatch.setattr(main_window, "run_in_background", lambda parent, work, done: done(work(), None))
    w, _ = sample_window(tmp_path / "pc")
    folder = tmp_path / "iCloudDrive" / "Balance Tracker"
    w.enable_sync(str(folder))

    def choose(dlg):
        dlg.phrase.setText("my sync passphrase")
        dlg.confirm.setText("my sync passphrase")
        dlg.accept()
        return 1

    monkeypatch.setattr(dialogs.SyncPassphraseDialog, "exec", choose)
    w.set_sync_passphrase()
    shared = folder / sync.SYNC_FILE
    raw = json.loads(shared.read_text())
    assert w.data.settings.sync_encrypt and raw["kind"] == "sync" and "Rent" not in shared.read_text()
    # a copy dropped in the folder without the passphrase is ignored and reported
    (folder / "BalanceTracker-sync 2.json").write_text(json.dumps(w.data.to_dict()))
    assert w.sync_in(force=True) == 0
    assert w.sync_refused and (folder / "BalanceTracker-sync 2.json").exists()
    w.go(5)
    assert "encrypted, so it was ignored" in w.pages[5].sync_status.text()
    # the key survives a restart (it's in secrets.json, not data.json)
    w2 = main_window.MainWindow(w.store, w.store.load())
    assert w2.sync_key == w.sync_key and "my sync passphrase" not in w.store.path.read_text()
    # turning encryption off writes the file in the clear again
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *a, **k: QtWidgets.QMessageBox.Yes)
    w.turn_off_sync_encryption()
    assert not w.data.settings.sync_encrypt and "Rent" in shared.read_text()


def test_export_backup_with_a_password(app, tmp_path, monkeypatch):
    out = tmp_path / "backup.json"

    def protect(dlg):
        dlg.password.setText("backup password")
        dlg.confirm.setText("backup password")
        dlg.accept()
        return 1

    monkeypatch.setattr(dialogs.BackupPasswordDialog, "exec", protect)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    w, _ = sample_window(tmp_path)
    w.export_backup()
    assert "Rent" not in out.read_text()
    monkeypatch.setattr("balance_tracker.ui.main_window.ask_password", lambda *a, **k: "backup password")
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", lambda self: self.clickedButton())
    restored = storage.read_backup(out, lambda problem: "backup password")
    assert {i.name for i in restored.items} == {"Pay", "Rent", "Phone"}


def test_undo_never_turns_sync_encryption_off(app, tmp_path):
    w, t = sample_window(tmp_path)
    w.snapshot()
    w.data.items.pop()
    w.commit(undoable=True)
    w.data.settings.sync_encrypt = True  # turned on in Settings after that change
    w.commit()
    w.undo()
    assert len(w.data.items) == 3 and w.data.settings.sync_encrypt
