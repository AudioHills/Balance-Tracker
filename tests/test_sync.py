from datetime import date

from balance_tracker.models import AppData, Checkpoint, Debt, RecurringItem, BILL, INCOME
from balance_tracker.storage import Store
from balance_tracker.sync import merge, same, stamp, sync_files, sync_payload, write_sync_file


def base():
    d = AppData()
    d.checkpoints.append(Checkpoint(date(2026, 10, 1), 100000, created_at="2026-10-01T08:00:00"))
    d.items.append(RecurringItem("Pay", 200000, INCOME, "biweekly", date(2026, 10, 9), id="pay"))
    d.items.append(RecurringItem("Rent", 150000, BILL, "monthly", date(2026, 10, 1), id="rent"))
    d.debts.append(Debt("Visa", 50000, 20.0, id="visa"))
    stamp(None, d, "2026-10-01T00:00:00.000Z")
    return d


def copy(d):
    return AppData.from_dict(d.to_dict())


def test_edits_on_both_sides_merge():
    pc = base()
    phone = copy(pc)
    # phone: changes rent, adds a bill, checks in
    prev = copy(phone)
    phone.item("rent").amount = 160000
    phone.items.append(RecurringItem("Gym", 5000, BILL, "monthly", date(2026, 10, 3), id="gym"))
    phone.add_checkpoint(Checkpoint(date(2026, 10, 5), 90000, created_at="2026-10-05T09:00:00"))
    stamp(prev, phone, "2026-10-05T09:00:00.000Z")
    # pc: changes the debt balance, deletes pay
    prev = copy(pc)
    pc.debt("visa").balance = 40000
    pc.items = [i for i in pc.items if i.id != "pay"]
    stamp(prev, pc, "2026-10-06T10:00:00.000Z")

    for a, b in ((pc, phone), (phone, pc)):  # merge is symmetric
        m = merge(a, b)
        assert m.item("rent").amount == 160000
        assert m.item("gym") is not None
        assert m.item("pay") is None
        assert m.debt("visa").balance == 40000
        assert len(m.checkpoints) == 2


def test_newer_edit_beats_older_delete():
    pc = base()
    phone = copy(pc)
    prev = copy(pc)
    pc.items = [i for i in pc.items if i.id != "rent"]
    stamp(prev, pc, "2026-10-02T00:00:00.000Z")
    prev = copy(phone)
    phone.item("rent").amount = 1
    stamp(prev, phone, "2026-10-03T00:00:00.000Z")
    assert merge(pc, phone).item("rent").amount == 1


def test_merge_is_idempotent_and_settings_follow_newest():
    pc = base()
    phone = copy(pc)
    prev = copy(phone)
    phone.settings.low_balance_threshold = 99900
    phone.settings.theme = "dark"  # per-device: never synced
    stamp(prev, phone, "2026-10-04T00:00:00.000Z")
    m = merge(pc, phone)
    assert m.settings.low_balance_threshold == 99900 and m.settings.theme == "system"
    assert same(merge(m, phone), m)


def test_same_day_checkins_keep_newest():
    pc = base()
    phone = copy(pc)
    pc.add_checkpoint(Checkpoint(date(2026, 10, 7), 1, created_at="2026-10-07T08:00:00"))
    phone.add_checkpoint(Checkpoint(date(2026, 10, 7), 2, created_at="2026-10-07T09:00:00"))
    m = merge(pc, phone)
    assert [c.balance for c in m.checkpoints if c.date == date(2026, 10, 7)] == [2]


def test_store_save_stamps_changes_and_deletions(tmp_path):
    s = Store(tmp_path)
    d = base()
    s.save(d)
    before = s.load().item("rent").updated
    d.item("rent").amount = 1
    d.items = [i for i in d.items if i.id != "pay"]
    s.save(d)
    after = s.load()
    assert after.item("rent").updated > before
    assert "pay" in after.deleted


def test_sync_file_hides_private_settings(tmp_path):
    d = base()
    d.settings.email_to = "me@x.com"
    d.settings.smtp_user = "me@x.com"
    write_sync_file(tmp_path, d)
    text = (tmp_path / "BalanceTracker-sync.json").read_text()
    assert "me@x.com" not in text and '"device": "pc"' in text
    (tmp_path / "BalanceTracker-sync 2.json").write_text(sync_payload(d))
    assert len(sync_files(tmp_path)) == 2
