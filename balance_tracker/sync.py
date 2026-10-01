"""Two-way sync with the iPhone web app through a file in iCloud Drive.

Every income/bill and debt carries an `updated` UTC timestamp, deletions leave a
tombstone in `AppData.deleted`, and the settings both devices share carry
`settings_updated`. `merge()` combines two copies record by record, keeping the
newest version of each, so edits made on either device survive. The same rules
are implemented in web/engine.js.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .models import AppData

SYNC_FILE = "BalanceTracker-sync.json"
SYNC_SUBFOLDER = "Balance Tracker"
TOMBSTONE_DAYS = 365

# Settings that follow you between devices (everything else is per-device).
SHARED_SETTINGS = ("currency_symbol", "low_balance_threshold", "forecast_months", "account_name",
                   "debt_strategy", "debt_mode", "debt_fixed_extra", "debt_in_forecast")
# Never written to the sync file.
PRIVATE_SETTINGS = ("email_enabled", "email_to", "smtp_host", "smtp_port", "smtp_user", "smtp_ssl",
                    "ntfy_enabled", "ntfy_topic", "notify_last_sent", "notify_task", "sync_enabled",
                    "sync_folder", "reminder_time", "notify_card", "notify_debts", "notify_bills",
                    "notify_paydays", "notify_low", "notify_days_before", "notify_time", "theme",
                    "prompt_on_open", "hide_balance")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _body(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "updated"}


def stamp(prev: Optional[AppData], cur: AppData, now: Optional[str] = None) -> None:
    """Mark what changed in `cur` since `prev` (the last saved copy)."""
    now = now or now_utc()
    for attr in ("items", "debts"):
        old = {x.id: _body(x.to_dict()) for x in getattr(prev, attr)} if prev else {}
        for x in getattr(cur, attr):
            if not x.updated or old.get(x.id) != _body(x.to_dict()):
                x.updated = now
                cur.deleted.pop(x.id, None)
        if prev:
            live = {x.id for x in getattr(cur, attr)}
            for gone in set(old) - live:
                cur.deleted.setdefault(gone, now)
    if prev:
        before = {c.id for c in prev.checkpoints}
        for c in cur.checkpoints:
            if c.id not in before:
                cur.deleted.pop(c.id, None)  # re-added (e.g. undo)
        live = {c.id for c in cur.checkpoints}
        for c in prev.checkpoints:
            if c.id not in live:
                cur.deleted.setdefault(c.id, now)
        if any(getattr(prev.settings, k) != getattr(cur.settings, k) for k in SHARED_SETTINGS):
            cur.settings_updated = now
    if not cur.settings_updated:
        cur.settings_updated = now
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_DAYS)).strftime("%Y-%m-%dT")
    cur.deleted = {k: v for k, v in cur.deleted.items() if v >= cutoff}


def merge(local: AppData, remote: AppData) -> AppData:
    """Combine two copies; the newest version of each record wins."""
    out = AppData.from_dict(local.to_dict())
    deleted = dict(local.deleted)
    for k, v in remote.deleted.items():
        if v > deleted.get(k, ""):
            deleted[k] = v

    def pick(mine: list, theirs: list) -> list:
        by_id = {x.id: x for x in mine}
        for x in theirs:
            if x.id not in by_id or x.updated > by_id[x.id].updated:
                by_id[x.id] = x
        return [x for x in by_id.values() if x.id not in deleted or deleted[x.id] < x.updated]

    out.items = pick(out.items, [type(x).from_dict(x.to_dict()) for x in remote.items])
    out.debts = pick(out.debts, [type(x).from_dict(x.to_dict()) for x in remote.debts])

    cps = {c.id: c for c in out.checkpoints}
    for c in remote.checkpoints:
        cps.setdefault(c.id, type(c).from_dict(c.to_dict()))
    by_date = {}
    for c in cps.values():
        if c.id in deleted:
            continue
        cur = by_date.get(c.date)
        if cur is None or c.created_at > cur.created_at:
            by_date[c.date] = c
    out.checkpoints = list(by_date.values())

    out.card_paid = sorted(set(local.card_paid) | set(remote.card_paid))
    out.deleted = deleted
    if remote.settings_updated > local.settings_updated:
        for k in SHARED_SETTINGS:
            setattr(out.settings, k, getattr(remote.settings, k))
        out.settings_updated = remote.settings_updated
    return out


def same(a: AppData, b: AppData) -> bool:
    da, db = a.to_dict(), b.to_dict()
    da.pop("saved_at", None)
    db.pop("saved_at", None)
    return json.dumps(da, sort_keys=True) == json.dumps(db, sort_keys=True)


# ---- the shared file -------------------------------------------------------
def icloud_drive() -> Optional[Path]:
    """The iCloud Drive folder from iCloud for Windows, if installed."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for name in ("iCloudDrive", "iCloud Drive"):
        p = home / name
        if p.is_dir():
            return p
    return None


def default_sync_folder() -> Optional[Path]:
    root = icloud_drive()
    return root / SYNC_SUBFOLDER if root else None


def sync_payload(data: AppData) -> str:
    d = data.to_dict()
    d["settings"] = {k: v for k, v in d["settings"].items() if k not in PRIVATE_SETTINGS}
    d["device"] = "pc"
    return json.dumps(d, indent=1)


def write_sync_file(folder: Path, data: AppData) -> None:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (SYNC_FILE + ".tmp")
    tmp.write_text(sync_payload(data), encoding="utf-8")
    os.replace(tmp, folder / SYNC_FILE)


def sync_files(folder: Path) -> list:
    """The sync file plus any copies iCloud or the phone created ("…-sync 2.json")."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("BalanceTracker-sync*.json") if p.is_file())
