"""Optional password lock for the desktop app.

The lock keeps other people who use this Windows account from opening Balance Tracker or
reading it over your shoulder after you step away. It isn't encryption: data.json is protected
by your Windows sign-in (and BitLocker/Device encryption, if the PC is stolen). The password is
stored only as a salted scrypt hash, itself encrypted with DPAPI in secrets.json.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import unicodedata
from dataclasses import asdict, dataclass

from . import secure_store

SECRET_NAME = "app_lock"
MIN_PASSWORD = 6
FREE_TRIES = 5  # wrong passwords before waits start
MAX_WAIT = 15 * 60
IDLE_CHOICES = (0, 1, 5, 15, 30, 60)  # minutes; 0 = never lock automatically
_SCRYPT = {"n": 2**15, "r": 8, "p": 1}  # ~32 MB and a fraction of a second per guess


def _hash(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    secret = unicodedata.normalize("NFC", password).encode("utf-8")
    return hashlib.scrypt(secret, salt=salt, n=n, r=r, p=p, maxmem=256 * 1024 * 1024, dklen=32)


def password_problem(password: str) -> str:
    """Why a new password isn't good enough, or "" if it's fine."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(set(password)) < 3:
        return "That's too easy to guess — mix in more different characters."
    return ""


@dataclass
class LockConfig:
    salt: str
    hash: str
    n: int = _SCRYPT["n"]
    r: int = _SCRYPT["r"]
    p: int = _SCRYPT["p"]
    idle_minutes: int = 5
    lock_on_minimize: bool = False
    fails: int = 0
    until: float = 0.0  # time.time() before which no password is accepted

    def wait_seconds(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return max(0, int(self.until - now + 0.999))

    @classmethod
    def from_dict(cls, d: dict) -> LockConfig:
        cfg = cls(salt=str(d["salt"]), hash=str(d["hash"]))
        for name in ("n", "r", "p", "idle_minutes", "fails"):
            if name in d:
                setattr(cfg, name, int(d[name]))
        cfg.until = float(d.get("until", 0))
        cfg.lock_on_minimize = bool(d.get("lock_on_minimize", False))
        if cfg.idle_minutes not in IDLE_CHOICES:
            cfg.idle_minutes = 5
        if not (2**10 <= cfg.n <= 2**20 and cfg.n & (cfg.n - 1) == 0 and 1 <= cfg.r <= 32 and 1 <= cfg.p <= 4):
            raise ValueError("Unsupported lock settings")
        return cfg


def load(folder) -> LockConfig | None:
    raw = secure_store.get_json(folder, SECRET_NAME)
    if not raw:
        return None
    try:
        return LockConfig.from_dict(raw)
    except (KeyError, TypeError, ValueError):
        return None


def save(folder, cfg: LockConfig) -> None:
    secure_store.put_json(folder, SECRET_NAME, asdict(cfg))


def set_password(folder, password: str, idle_minutes: int = 5, lock_on_minimize: bool = False) -> LockConfig:
    salt = os.urandom(16)
    cfg = LockConfig(salt=salt.hex(), hash=_hash(password, salt, **_SCRYPT).hex(), idle_minutes=idle_minutes,
                     lock_on_minimize=lock_on_minimize)
    save(folder, cfg)
    return cfg


def remove(folder) -> None:
    secure_store.put_json(folder, SECRET_NAME, None)


def check(folder, password: str, now: float | None = None) -> bool:
    """Is this the password? Wrong guesses earn growing waits (30 s, 1 min, 2 min … 15 min)."""
    cfg = load(folder)
    if cfg is None:
        return True
    now = time.time() if now is None else now
    if cfg.wait_seconds(now):
        return False
    ok = hmac.compare_digest(_hash(password, bytes.fromhex(cfg.salt), cfg.n, cfg.r, cfg.p).hex(), cfg.hash)
    if ok:
        cfg.fails, cfg.until = 0, 0.0
    else:
        cfg.fails += 1
        if cfg.fails >= FREE_TRIES:
            cfg.until = now + min(MAX_WAIT, 30 * 2 ** (cfg.fails - FREE_TRIES))
    save(folder, cfg)
    return ok
