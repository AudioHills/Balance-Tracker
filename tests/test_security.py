"""Encryption, the secrets file, the app lock, and the input checks that keep hostile files harmless."""
import json
import os
import sys
from datetime import date

import pytest

from balance_tracker import applock, encryption, notify, secure_store, storage, sync, updates
from balance_tracker.encryption import FileKey, WrongPassword
from balance_tracker.models import BILL, AppData, Checkpoint, RecurringItem, Settings, clean_symbol
from balance_tracker.reminders import _esc

FAST = encryption.MIN_ITERATIONS  # keep key stretching quick in tests


def sample() -> AppData:
    d = AppData()
    d.checkpoints.append(Checkpoint(date(2026, 10, 1), 100000, created_at="2026-10-01T08:00:00"))
    d.items.append(RecurringItem("Rent", 150000, BILL, "monthly", date(2026, 10, 1), id="rent"))
    sync.stamp(None, d, "2026-10-01T00:00:00.000Z")
    return d


# ---- encryption ---------------------------------------------------------
def test_seal_and_open():
    key = FileKey.derive("correct horse battery", iterations=FAST)
    env = json.loads(encryption.seal('{"hello": "wörld"}', key, "backup"))
    assert env["kind"] == "backup" and env["iterations"] == FAST and "wörld" not in json.dumps(env)
    assert encryption.is_encrypted(env)
    assert encryption.open_with_key(env, key) == '{"hello": "wörld"}'
    text, again = encryption.open_with_passphrase(env, "correct horse battery")
    assert text == '{"hello": "wörld"}' and again.key == key.key
    # every file gets a fresh IV
    ivs = {json.loads(encryption.seal("x", key, "backup"))["iv"] for _ in range(2)}
    assert len(ivs) == 2


def test_wrong_passphrase_and_tampering_are_refused():
    key = FileKey.derive("correct horse battery", iterations=FAST)
    env = json.loads(encryption.seal('{"a": 1}', key, "sync"))
    with pytest.raises(WrongPassword):
        encryption.open_with_passphrase(env, "correct horse batterY")
    data = bytearray(encryption._unb64(env["data"]))
    data[3] ^= 1
    with pytest.raises(WrongPassword):
        encryption.open_with_key({**env, "data": encryption._b64(bytes(data))}, key)
    with pytest.raises(WrongPassword):  # a sync file can't be passed off as a backup (or vice versa)
        encryption.open_with_key({**env, "kind": "backup"}, key)
    other = FileKey.derive("correct horse battery", iterations=FAST)  # same passphrase, different salt
    assert not other.fits(env)
    with pytest.raises(WrongPassword):
        encryption.open_with_key(env, other)


def test_unsupported_or_damaged_files_are_refused():
    key = FileKey.derive("pw-pw-pw-pw", iterations=FAST)
    env = json.loads(encryption.seal("{}", key, "backup"))
    for bad in ({**env, "iterations": 1000}, {**env, "iterations": 10**9}, {**env, "kdf": "MD5"},
                {**env, "cipher": "ROT13"}, {**env, "kind": "other"}, {**env, "iv": "AAAA"}, {**env, "salt": "!!"}):
        with pytest.raises(ValueError):
            encryption.open_with_passphrase(bad, "pw-pw-pw-pw")


def test_passphrases():
    assert encryption.passphrase_problem("short")
    assert encryption.passphrase_problem("aaaaaaaaaaaa")
    assert not encryption.passphrase_problem("long enough phrase")
    p = encryption.suggest_passphrase()
    assert not encryption.passphrase_problem(p) and len(p) == 24
    # the same passphrase typed with a composed or decomposed accent gives the same key
    salt = os.urandom(16)
    assert FileKey.derive("café", salt, FAST).key == FileKey.derive("café", salt, FAST).key


# ---- sync file ------------------------------------------------------------
def test_encrypted_sync_round_trip(tmp_path):
    key = FileKey.derive("sync passphrase", iterations=FAST)
    d = sample()
    sync.write_sync_file(tmp_path, d, key)
    text = (tmp_path / sync.SYNC_FILE).read_text()
    assert "Rent" not in text and json.loads(text)["kind"] == "sync"
    phone = AppData.from_dict(json.loads(encryption.open_with_key(json.loads(text), key)))
    prev = AppData.from_dict(phone.to_dict())
    phone.items.append(RecurringItem("Gym", 5000, BILL, "monthly", date(2026, 10, 3), id="gym"))
    sync.stamp(prev, phone, "2026-10-05T00:00:00.000Z")
    (tmp_path / "BalanceTracker-sync 2.json").write_text(encryption.seal(json.dumps(phone.to_dict()), key, "sync"))
    r = sync.pull_folder(tmp_path, d, key, require_encrypted=True)
    assert r.changed and not r.problems and {i.name for i in r.data.items} == {"Rent", "Gym"}
    assert [p.name for p in r.copies] == ["BalanceTracker-sync 2.json"]


def test_files_that_dont_belong_are_refused_not_merged(tmp_path):
    key = FileKey.derive("sync passphrase", iterations=FAST)
    d = sample()
    sync.write_sync_file(tmp_path, d, key)
    intruder = sample()
    intruder.items.append(RecurringItem("Fake bill", 99999, BILL, "monthly", date(2026, 10, 3), id="fake"))
    sync.stamp(sample(), intruder, "2099-01-01T00:00:00.000Z")
    (tmp_path / "BalanceTracker-sync 2.json").write_text(json.dumps(intruder.to_dict()))  # not encrypted
    wrong = FileKey.derive("someone else", iterations=FAST)
    (tmp_path / "BalanceTracker-sync 3.json").write_text(encryption.seal(json.dumps(intruder.to_dict()), wrong, "sync"))
    r = sync.pull_folder(tmp_path, d, key, require_encrypted=True)
    assert not r.changed and not r.copies and len(r.problems) == 2
    assert any("isn't encrypted" in p for p in r.problems) and any("different passphrase" in p for p in r.problems)
    # without a key, an encrypted file is reported rather than silently skipped
    r = sync.pull_folder(tmp_path, d)
    assert any("encrypted" in p for p in r.problems)


def test_oversized_sync_files_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "MAX_SYNC_BYTES", 100)
    (tmp_path / sync.SYNC_FILE).write_text(json.dumps(sample().to_dict()))
    r = sync.pull_folder(tmp_path, AppData())
    assert not r.changed and "too big" in r.problems[0]


def test_pc_only_settings_never_reach_the_sync_file():
    d = sample()
    d.settings.email_to, d.settings.ntfy_topic, d.settings.sync_encrypt = "me@example.com", "bt-secret-topic", True
    payload = json.loads(sync.sync_payload(d))
    assert not set(payload["settings"]) & set(sync.PRIVATE_SETTINGS)


# ---- backups --------------------------------------------------------------
def test_password_protected_backup(tmp_path):
    p = tmp_path / "backup.json"
    storage.export_backup(sample(), p, "backup password")
    assert "Rent" not in p.read_text()
    with pytest.raises(ValueError, match="password"):
        storage.read_backup(p)
    answers = iter(["wrong", "backup password"])
    seen = []

    def ask(problem):
        seen.append(problem)
        return next(answers)

    assert [i.name for i in storage.read_backup(p, ask).items] == ["Rent"]
    assert seen == ["", "That password didn't work. Try again."]
    with pytest.raises(storage.ImportCancelled):
        storage.read_backup(p, lambda problem: None)


def test_sync_file_imports_with_the_stored_key(tmp_path):
    key = FileKey.derive("sync passphrase", iterations=FAST)
    sync.write_sync_file(tmp_path, sample(), key)
    d = storage.read_backup(tmp_path / sync.SYNC_FILE, keys=[None, key])
    assert [i.name for i in d.items] == ["Rent"]


def test_huge_imports_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MAX_IMPORT_BYTES", 10)
    p = tmp_path / "b.json"
    storage.export_backup(sample(), p)
    with pytest.raises(ValueError, match="too big"):
        storage.read_backup(p)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_files_are_private_to_the_user(tmp_path):
    store = storage.Store(tmp_path)
    store.save(sample())
    secure_store.put(tmp_path, "x", "y")
    for p in (store.path, tmp_path / secure_store.SECRETS_FILE, *store.backup_dir.glob("*.json")):
        assert p.stat().st_mode & 0o077 == 0, p


# ---- secrets file ---------------------------------------------------------
def test_secure_store(tmp_path):
    secure_store.put(tmp_path, "smtp_password", "abcd efgh")
    secure_store.put_json(tmp_path, "sync_key", {"k": 1})
    raw = (tmp_path / secure_store.SECRETS_FILE).read_text()
    assert "abcd" not in raw and '"k"' not in raw
    assert secure_store.get(tmp_path, "smtp_password") == "abcd efgh"
    assert secure_store.get_json(tmp_path, "sync_key") == {"k": 1}
    secure_store.put(tmp_path, "smtp_password", "")
    assert secure_store.get(tmp_path, "smtp_password") == "" and secure_store.get_json(tmp_path, "sync_key") == {"k": 1}
    (tmp_path / secure_store.SECRETS_FILE).write_text("{broken")
    assert secure_store.get(tmp_path, "sync_key") == ""


def test_secrets_never_go_into_backups_or_sync(tmp_path):
    store = storage.Store(tmp_path)
    notify.save_password(tmp_path, "app-password-123")
    d = sample()
    store.save(d)
    for text in (store.path.read_text(), sync.sync_payload(d)):
        assert "app-password-123" not in text and "smtp_password" not in text


# ---- app lock -------------------------------------------------------------
def test_app_lock(tmp_path):
    assert applock.load(tmp_path) is None and applock.check(tmp_path, "anything")
    assert applock.password_problem("abc") and applock.password_problem("aaaaaaaa")
    applock.set_password(tmp_path, "open sesame", idle_minutes=15)
    cfg = applock.load(tmp_path)
    assert cfg.idle_minutes == 15 and "open sesame" not in (tmp_path / secure_store.SECRETS_FILE).read_text()
    assert applock.check(tmp_path, "open sesame")
    assert not applock.check(tmp_path, "open sesamE")


def test_app_lock_waits_after_wrong_passwords(tmp_path):
    applock.set_password(tmp_path, "open sesame")
    now = 1_000_000.0
    for _ in range(applock.FREE_TRIES):
        assert not applock.check(tmp_path, "nope", now)
    assert applock.load(tmp_path).wait_seconds(now) == 30
    assert not applock.check(tmp_path, "open sesame", now + 10)  # even the right one, during the wait
    assert applock.check(tmp_path, "open sesame", now + 31)
    assert applock.load(tmp_path).fails == 0
    applock.remove(tmp_path)
    assert applock.load(tmp_path) is None


def test_tampered_lock_settings_are_ignored(tmp_path):
    applock.set_password(tmp_path, "open sesame")
    cfg = secure_store.get_json(tmp_path, applock.SECRET_NAME)
    secure_store.put_json(tmp_path, applock.SECRET_NAME, {**cfg, "n": 2**30})  # would take forever per guess
    assert applock.load(tmp_path) is None


# ---- reminders ------------------------------------------------------------
def test_ntfy_topics_must_be_unguessable():
    assert notify.ntfy_topic_problem("money")
    assert notify.ntfy_topic_problem("bad topic with spaces and length")
    assert not notify.ntfy_topic_problem(notify.new_ntfy_topic())
    assert notify.new_ntfy_topic() != notify.new_ntfy_topic()
    with pytest.raises(ValueError):
        notify.send_ntfy("money", "t", "x")


def test_email_headers_cant_be_split():
    assert notify._header("Pay Visa\r\nBcc: someone@example.com") == "Pay Visa Bcc: someone@example.com"

    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context):
            sent["tls"] = context.verify_mode

        def login(self, user, pw):
            pass

        def send_message(self, msg):
            sent["subject"] = msg["Subject"]

    import smtplib
    import ssl
    s = Settings(email_to="me@example.com", smtp_host="smtp.example.com")
    orig = smtplib.SMTP
    smtplib.SMTP = FakeSMTP
    try:
        notify.send_email(s, "pw", "Rent\nBcc: x@example.com", "body")
    finally:
        smtplib.SMTP = orig
    assert "\n" not in sent["subject"] and sent["tls"] == ssl.CERT_REQUIRED  # TLS with a verified certificate


# ---- hostile data ---------------------------------------------------------
def test_currency_symbol_cant_carry_markup():
    assert clean_symbol('<img src=x onerror="alert(1)">') == "img "
    assert clean_symbol("  € ") == "€" and clean_symbol("") == "$" and clean_symbol("<>&") == "$"
    assert Settings.from_dict({"currency_symbol": "<b>$</b>"}).currency_symbol == "b$/b"


def test_csv_cells_cant_run_formulas(tmp_path):
    from balance_tracker.forecast import Entry
    e = Entry(date(2026, 10, 1), "bill", '=HYPERLINK("http://evil.example","Click")', -500, 1000, category="@SUM(A1)")
    p = tmp_path / "out.csv"
    storage.export_ledger_csv([e], p)
    text = p.read_text(encoding="utf-8-sig")
    assert "'=HYPERLINK" in text and "'@SUM" in text and ",-5.00," in text  # amounts are left alone
    assert storage.csv_text("Rent") == "Rent" and storage.csv_text("-5 refund") == "'-5 refund"


def test_calendar_text_cant_add_lines():
    assert "\r" not in _esc("Rent\r\nATTACH:http://evil.example")


def test_update_link_stays_on_this_repo():
    assert updates.safe_release_url("https://evil.example/BalanceTracker.exe") == updates.RELEASES_URL
