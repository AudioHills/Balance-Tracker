import json
import logging
from datetime import date

from balance_tracker import logs, storage, updates
from balance_tracker.models import BILL, AppData, Checkpoint, RecurringItem
from balance_tracker.storage import Backup, Store
from balance_tracker.sync import SYNC_FILE, pull_folder, stamp, sync_payload


def sample():
    d = AppData()
    d.checkpoints.append(Checkpoint(date(2026, 10, 1), 100000))
    d.items.append(RecurringItem("Rent", 150000, BILL, "monthly", date(2026, 10, 1), id="rent"))
    return d


def test_backups_are_listed_newest_first_with_labels(tmp_path):
    s = Store(tmp_path)
    s.backup_dir.mkdir()
    for name in ("auto-2026-10-01.json", "auto-2026-10-03.json", "before-restore-2026-10-02_093000.json",
                 "merged-20261004-071500-BalanceTracker-sync 2.json", "notes.json"):
        (s.backup_dir / name).write_text("{}")
    found = s.backups()
    assert [b.kind for b in found] == ["merged", "auto", "before-restore", "auto"]
    assert found[0].label == "iPhone changes merged · Sun Oct 4, 2026 07:15"
    assert found[1].label == "Automatic backup · Sat Oct 3, 2026"
    assert [p.name for p in s.auto_backups()] == ["auto-2026-10-03.json", "auto-2026-10-01.json"]
    assert Backup.from_path(s.backup_dir / "notes.json") is None


def test_safety_backups_and_sync_copies_are_pruned(tmp_path, monkeypatch):
    s = Store(tmp_path)
    s.backup_dir.mkdir()
    for k in range(storage.SAFETY_BACKUPS_KEPT + 3):
        (s.backup_dir / f"before-restore-2026-01-{k + 1:02d}_120000.json").write_text("{}")
    s.safety_backup(sample())
    kept = [b for b in s.backups() if b.kind == "before-restore"]
    assert len(kept) == storage.SAFETY_BACKUPS_KEPT and kept[0].when.date() == date.today()

    for k in range(storage.SYNC_COPIES_KEPT + 2):
        (s.backup_dir / f"merged-202601{k + 1:02d}-120000-old.json").write_text("{}")
    copy = tmp_path / "BalanceTracker-sync 2.json"
    copy.write_text("{}")
    s.archive_sync_copy(copy)
    assert not copy.exists()
    assert len([b for b in s.backups() if b.kind == "merged"]) == storage.SYNC_COPIES_KEPT


def test_pull_folder_merges_phone_copies(tmp_path):
    pc = sample()
    stamp(None, pc, "2026-10-01T00:00:00.000Z")
    (tmp_path / SYNC_FILE).write_text(sync_payload(pc))
    phone = AppData.from_dict(pc.to_dict())
    prev = AppData.from_dict(phone.to_dict())
    phone.items.append(RecurringItem("Gym", 5000, BILL, "monthly", date(2026, 10, 3), id="gym"))
    stamp(prev, phone, "2026-10-02T00:00:00.000Z")
    (tmp_path / "BalanceTracker-sync 2.json").write_text(json.dumps(phone.to_dict()))
    (tmp_path / "BalanceTracker-sync 3.json").write_text("{half-downloaded")

    result = pull_folder(tmp_path, pc)
    assert result.changed and result.data.item("gym") is not None
    assert [p.name for p in result.copies] == ["BalanceTracker-sync 2.json"]  # unreadable one left for later
    assert not pull_folder(tmp_path, result.data).changed


def test_log_file_is_created_once(tmp_path):
    logger = logging.getLogger("balance_tracker")
    before = list(logger.handlers)
    try:
        path = logs.setup(tmp_path)
        assert logs.setup(tmp_path) == path and len(logger.handlers) == len(before) + 1
        logging.getLogger("balance_tracker.test").warning("hello")
        for h in logger.handlers:
            h.flush()
        assert "hello" in path.read_text(encoding="utf-8")
    finally:
        for h in set(logger.handlers) - set(before):
            logger.removeHandler(h)
            h.close()


def test_store_logs_a_failed_backup(tmp_path, caplog):
    s = Store(tmp_path)
    s.backup_dir.parent.mkdir(parents=True, exist_ok=True)
    s.backup_dir.write_text("not a folder")  # makes the backup write fail
    s.save(sample())
    assert s.load().item("rent") is not None
    assert "Automatic backup failed" in caplog.text


def test_version_comparison():
    assert updates.parse_version("v2.10.1") == (2, 10, 1)
    assert updates.parse_version("2.1.0-beta") == (2, 1, 0)
    assert updates.is_newer("2.0.1", "2.0.0") and updates.is_newer("v3", "2.9.9")
    assert not updates.is_newer("2.0", "2.0.0") and not updates.is_newer("1.9.9", "2.0.0")


def test_latest_release_reads_the_github_reply():
    class Reply:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.body).encode()

    seen = {}

    def opener(req, timeout):
        seen["url"], seen["agent"] = req.full_url, req.get_header("User-agent")
        return Reply({"tag_name": "v2.1.0", "html_url": "https://example.com/r", "name": "Balance Tracker 2.1.0"})

    r = updates.latest_release(opener=opener)
    assert (r.version, r.url) == ("2.1.0", "https://example.com/r")
    assert seen["url"] == updates.API_URL and seen["agent"].startswith("BalanceTracker/")


def test_malformed_backup_names_are_ignored(tmp_path):
    assert Backup.from_path(tmp_path / "auto-2026-13-40.json") is None
