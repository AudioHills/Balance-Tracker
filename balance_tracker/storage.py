"""Saving, loading, automatic backups and import/export."""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from .models import AppData

APP_DIR_NAME = "BalanceTracker"
DATA_FILE = "data.json"
AUTO_BACKUPS_KEPT = 30


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Store:
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

    def save(self, data: AppData) -> None:
        text = json.dumps(data.to_dict(), indent=2)
        _atomic_write(self.path, text)
        self._auto_backup(text)

    # ---- automatic daily backups -------------------------------------
    def _auto_backup(self, text: str) -> None:
        """Keep one rolling snapshot per day for the last AUTO_BACKUPS_KEPT days."""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(self.backup_dir / f"auto-{date.today().isoformat()}.json", text)
            autos = sorted(self.backup_dir.glob("auto-*.json"))
            for old in autos[:-AUTO_BACKUPS_KEPT]:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # backups are best-effort; never block a save

    def auto_backups(self) -> list:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob("*.json"), reverse=True)

    def safety_backup(self, data: AppData) -> Path:
        """Snapshot taken right before a destructive action (import/reset)."""
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        p = self.backup_dir / f"before-restore-{stamp}.json"
        _atomic_write(p, json.dumps(data.to_dict(), indent=2))
        return p


# ---- manual export / import ------------------------------------------
def export_backup(data: AppData, path: Path) -> None:
    _atomic_write(Path(path), json.dumps(data.to_dict(), indent=2))


def read_backup(path: Path) -> AppData:
    with open(path, encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"The file isn't valid JSON ({e.msg}).") from e
    return AppData.from_dict(raw)


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


def export_ledger_csv(entries, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel opens it cleanly
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Category", "Type", "Amount", "Balance"])
        for e in entries:
            w.writerow([e.date.isoformat(), e.description, e.category, e.kind,
                        f"{e.amount / 100:.2f}", f"{e.balance / 100:.2f}"])
