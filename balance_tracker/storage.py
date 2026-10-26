"""Saving, loading, automatic backups and import/export."""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import encryption
from .encryption import FileKey
from .formatting import full_date
from .models import AppData
from .sync import stamp

log = logging.getLogger(__name__)

APP_DIR_NAME = "BalanceTracker"
DATA_FILE = "data.json"

# How many of each kind of backup to keep in the backups folder
AUTO_BACKUPS_KEPT = 30  # one per day
SAFETY_BACKUPS_KEPT = 10  # taken before a restore or erase
SYNC_COPIES_KEPT = 20  # iPhone copies merged in from the sync folder
MAX_IMPORT_BYTES = 20 * 1024 * 1024  # far more than years of data; anything bigger isn't a backup

_BACKUP_NAME = re.compile(r"^(auto|before-restore|merged)-(\d{4}-?\d{2}-?\d{2})(?:[_-](\d{6}))?")


def default_data_dir() -> Path:
    override = os.environ.get("BALANCE_TRACKER_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_DIR_NAME


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file, so a crash never leaves half a file. New files are readable only
    by this user where the OS supports it (on Windows, the per-user AppData folder already is)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass(frozen=True)
class Backup:
    """A file in the backups folder."""

    path: Path
    kind: str  # auto | before-restore | merged
    when: datetime

    @property
    def label(self) -> str:
        time = "" if self.kind == "auto" else f" {self.when:%H:%M}"
        title = {"auto": "Automatic backup", "before-restore": "Before a restore",
                 "merged": "iPhone changes merged"}[self.kind]
        return f"{title} · {full_date(self.when.date())}{time}"

    @classmethod
    def from_path(cls, path: Path) -> Backup | None:
        m = _BACKUP_NAME.match(path.name)
        if not m:
            return None
        kind, day, clock = m.groups()
        try:
            when = datetime.strptime(day.replace("-", "") + (clock or "000000"), "%Y%m%d%H%M%S")
        except ValueError:
            return None
        return cls(path, kind, when)


class Store:
    """The data file plus its backups folder."""

    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder) if folder else default_data_dir()
        self.path = self.folder / DATA_FILE
        self.backup_dir = self.folder / "backups"

    # ---- main data file ----------------------------------------------
    def load(self) -> AppData:
        if not self.path.exists():
            return AppData()
        with open(self.path, encoding="utf-8") as f:
            return AppData.from_dict(json.load(f))

    def save(self, data: AppData, restamp: bool = True) -> None:
        """Save. `restamp=False` stores merged sync data as-is (its timestamps are already right)."""
        # The background reminder task may have sent today's digest since this copy was
        # loaded; never move "last sent" backwards (that could send a duplicate email).
        prev = None
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            on_disk = raw.get("settings", {}).get("notify_last_sent", "")
            if on_disk > data.settings.notify_last_sent:
                data.settings.notify_last_sent = on_disk
            prev = AppData.from_dict(raw)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError, KeyError, TypeError) as e:
            log.warning("Previous data file unreadable while saving (%s); saving anyway", e)
        if restamp:
            stamp(prev, data)  # timestamps + deletion markers for iPhone sync
        text = json.dumps(data.to_dict(), indent=2)
        _atomic_write(self.path, text)
        self._auto_backup(text)

    # ---- automatic daily backups -------------------------------------
    def _auto_backup(self, text: str) -> None:
        """Keep one rolling snapshot per day for the last AUTO_BACKUPS_KEPT days."""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(self.backup_dir / f"auto-{date.today().isoformat()}.json", text)
            self._prune("auto", AUTO_BACKUPS_KEPT)
        except OSError as e:
            log.warning("Automatic backup failed: %s", e)  # best-effort; never block a save

    def backups(self) -> list[Backup]:
        """Every backup in the backups folder, newest first."""
        if not self.backup_dir.exists():
            return []
        found = (Backup.from_path(p) for p in self.backup_dir.glob("*.json"))
        return sorted((b for b in found if b is not None), key=lambda b: b.when, reverse=True)

    def auto_backups(self) -> list[Path]:
        """The daily automatic backups, newest first."""
        return [b.path for b in self.backups() if b.kind == "auto"]

    def _prune(self, kind: str, keep: int) -> None:
        for old in [b for b in self.backups() if b.kind == kind][keep:]:
            old.path.unlink(missing_ok=True)

    def safety_backup(self, data: AppData) -> Path:
        """Snapshot taken right before a destructive action (import/reset)."""
        p = self.backup_dir / f"before-restore-{datetime.now():%Y-%m-%d_%H%M%S}.json"
        _atomic_write(p, json.dumps(data.to_dict(), indent=2))
        self._prune("before-restore", SAFETY_BACKUPS_KEPT)
        return p

    def archive_sync_copy(self, path: Path) -> None:
        """Move a phone copy that has been merged (e.g. "BalanceTracker-sync 2.json") into backups."""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(self.backup_dir / f"merged-{datetime.now():%Y%m%d-%H%M%S}-{path.name}"))
            self._prune("merged", SYNC_COPIES_KEPT)
        except OSError as e:
            log.warning("Couldn't tidy away merged sync copy %s: %s", path, e)


# ---- manual export / import ------------------------------------------
class ImportCancelled(Exception):
    """The user didn't enter the password for a protected backup."""


def export_backup(data: AppData, path: Path, password: str = "") -> None:
    """Save a backup file, encrypted with `password` if one is given."""
    text = json.dumps(data.to_dict(), indent=2)
    if password:
        text = encryption.seal(text, FileKey.derive(password), "backup")
    _atomic_write(Path(path), text)


def read_backup(path: Path, ask_password=None, keys=()) -> AppData:
    """Read a backup (or sync) file. For an encrypted one, a matching key from `keys` is tried first,
    then `ask_password(problem)` is called until it returns the right password or None (cancel)."""
    path = Path(path)
    if path.stat().st_size > MAX_IMPORT_BYTES:
        raise ValueError("The file is too big to be a Balance Tracker backup.")
    with open(path, encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"The file isn't valid JSON ({e.msg}).") from e
    if encryption.is_encrypted(raw):
        raw = json.loads(_decrypt(raw, ask_password, keys))
    return AppData.from_dict(raw)


def _decrypt(envelope: dict, ask_password, keys) -> str:
    for key in keys:
        if key is not None and key.fits(envelope):
            return encryption.open_with_key(envelope, key)
    if ask_password is None:
        raise ValueError("This file is password-protected.")
    problem = ""
    while True:
        password = ask_password(problem)
        if password is None:
            raise ImportCancelled()
        try:
            return encryption.open_with_passphrase(envelope, password)[0]
        except encryption.WrongPassword:
            problem = "That password didn't work. Try again."


def merge_data(current: AppData, incoming: AppData) -> AppData:
    """Add items/check-ins from `incoming` that aren't already present (by id)."""
    have_items = {i.id for i in current.items}
    have_cps = {c.date for c in current.checkpoints}
    for i in incoming.items:
        if i.id not in have_items:
            current.items.append(i)
    for c in incoming.checkpoints:
        if c.date not in have_cps:
            current.checkpoints.append(c)
    have_debts = {d.id for d in current.debts}
    for d in incoming.debts:
        if d.id not in have_debts:
            current.debts.append(d)
    return current


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_text(value: str) -> str:
    """Text for a CSV cell that Excel/Numbers won't run as a formula (CSV injection): a name like
    "=HYPERLINK(...)" from a sync file becomes "'=HYPERLINK(...)". Mirrors csvText() in web/engine.js."""
    return "'" + value if value.startswith(_FORMULA_START) else value


def export_ledger_csv(entries, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel opens it cleanly
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Category", "Type", "Amount", "Balance"])
        for e in entries:
            w.writerow([e.date.isoformat(), csv_text(e.description), csv_text(e.category), e.kind,
                        f"{e.amount / 100:.2f}", f"{e.balance / 100:.2f}"])
