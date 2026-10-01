import xml.etree.ElementTree as ET
from datetime import date, datetime

from balance_tracker import notify
from balance_tracker.models import AppData, Checkpoint, Debt, RecurringItem, BILL, INCOME
from balance_tracker.storage import Store

TODAY = date(2026, 10, 12)


def sample():
    d = AppData()
    d.checkpoints.append(Checkpoint(date(2026, 10, 1), 300000))
    visa = Debt("Visa", 100000, 20.0, due_day=13, min_percent=1)
    d.debts.append(visa)
    d.items.append(RecurringItem("Spotify", 1199, BILL, "monthly", date(2026, 10, 12), paid_with=visa.id))
    d.items.append(RecurringItem("Rent", 150000, BILL, "monthly", date(2026, 10, 13)))
    d.items.append(RecurringItem("Pay", 250000, INCOME, "biweekly", date(2026, 10, 12)))
    s = d.settings
    s.email_enabled, s.email_to, s.smtp_user = True, "me@example.com", "me@example.com"
    return d, visa


def test_compose_digest():
    d, _ = sample()
    d.settings.notify_bills = d.settings.notify_paydays = True
    dg = notify.compose(d, TODAY)
    texts = [t for _, t, _ in dg.lines]
    assert texts[0] == "Pay Visa $11.99 — Spotify"
    assert any(t.startswith("Visa payment") and "tomorrow" in t for t in texts)
    assert any("Rent $1,500.00 comes out tomorrow" == t for t in texts)
    assert any("Pay $2,500.00 lands today" == t for t in texts)
    assert dg.subject.startswith("Pay Visa $11.99 — Spotify (+")
    assert "<table" in dg.html and "Spotify" in dg.text


def test_paid_card_charges_are_skipped_and_empty_days_send_nothing():
    d, _ = sample()
    d.card_paid.append(f"{d.items[0].id}|2026-10-12")
    d.settings.notify_debts = False
    assert notify.compose(d, TODAY) is None


def test_unpaid_card_charge_keeps_nagging():
    d, _ = sample()
    d.settings.notify_debts = False
    dg = notify.compose(d, date(2026, 10, 14))
    assert "still unpaid" in dg.lines[0][1]


def test_send_email_uses_starttls_and_login(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"] = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self, context=None): sent["tls"] = True
        def login(self, u, p): sent["login"] = (u, p)
        def send_message(self, msg): sent["msg"] = msg

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    d, _ = sample()
    notify.send_email(d.settings, "app-pass", "Hi", "text", "<b>html</b>")
    assert sent["host"] == ("smtp.gmail.com", 587) and sent["tls"]
    assert sent["login"] == ("me@example.com", "app-pass")
    assert sent["msg"]["To"] == "me@example.com"


def test_password_roundtrip(tmp_path):
    notify.save_password(tmp_path, "abcd efgh")
    assert notify.load_password(tmp_path) == "abcd efgh"
    assert "abcd" not in (tmp_path / "secrets.json").read_text()


def test_run_daily_sends_once(tmp_path, monkeypatch):
    d, _ = sample()
    store = Store(tmp_path)
    store.save(d)
    calls = []
    monkeypatch.setattr(notify, "deliver", lambda data, folder, dg: calls.append(dg.subject) or [])
    assert notify.run_daily(store, datetime(2026, 10, 12, 7, 0)) == "not due"
    assert notify.run_daily(store, datetime(2026, 10, 12, 8, 5)) == "sent"
    assert notify.run_daily(store, datetime(2026, 10, 12, 9, 0)) == "not due"
    assert len(calls) == 1 and store.load().settings.notify_last_sent == "2026-10-12"
    # a stale copy saved later must not move "last sent" backwards
    stale = AppData.from_dict(d.to_dict())
    store.save(stale)
    assert store.load().settings.notify_last_sent == "2026-10-12"


def test_failed_delivery_retries_later(tmp_path, monkeypatch):
    d, _ = sample()
    store = Store(tmp_path)
    store.save(d)
    monkeypatch.setattr(notify, "deliver", lambda *a: ["Email: bad password"])
    assert "bad password" in notify.run_daily(store, datetime(2026, 10, 12, 8, 5))
    assert store.load().settings.notify_last_sent == ""


def test_task_xml_is_valid():
    xml = notify.task_xml("08:00", r"C:\Apps\BalanceTracker.exe", "--send-reminders")
    root = ET.fromstring(xml.replace('encoding="UTF-16"', ""))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:StartWhenAvailable", ns).text == "true"
    assert root.find(".//t:Command", ns).text.endswith("BalanceTracker.exe")
    assert root.find(".//t:LogonTrigger", ns) is not None
