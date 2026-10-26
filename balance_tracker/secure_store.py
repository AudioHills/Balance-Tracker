"""Secrets kept on this PC: the email app password, the sync-file key and the app lock.

They live in ``secrets.json`` in the data folder, apart from ``data.json``, so they are never
part of backups, exports or the iPhone sync file. Each value is encrypted with Windows DPAPI,
which ties it to this Windows account on this PC, plus an app-specific entropy value so other
programs can't decrypt it just by asking DPAPI for "the user's" secrets.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

SECRETS_FILE = "secrets.json"
_ENTROPY = b"BalanceTracker secrets v2"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1  # fail rather than ever show a Windows prompt (the reminder task has no UI)


def _dpapi(data: bytes, encrypt: bool, entropy: bytes | None) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes) -> tuple[Blob, object]:
        buf = ctypes.create_string_buffer(raw, len(raw))
        return Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    inp, _keep = blob(data)
    ent, _keep_ent = blob(entropy) if entropy else (None, None)
    out = Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, ctypes.byref(ent) if ent else None, None, None,
              _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise OSError("Windows could not protect the secret" if encrypt else "Windows could not unlock the secret")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(secret: str) -> str:
    raw = secret.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi2:" + base64.b64encode(_dpapi(raw, True, _ENTROPY)).decode()
    return "plain:" + base64.b64encode(raw).decode()  # non-Windows development and tests only


def unprotect(token: str) -> str:
    if not token:
        return ""
    kind, _, body = token.partition(":")
    raw = base64.b64decode(body)
    if kind == "dpapi2":
        return _dpapi(raw, False, _ENTROPY).decode("utf-8")
    if kind == "dpapi":  # written by 2.0 and earlier, without entropy
        return _dpapi(raw, False, None).decode("utf-8")
    if kind == "plain":
        return raw.decode("utf-8")
    raise ValueError(f"Unknown secret format {kind!r}")


def _path(folder: Path) -> Path:
    return Path(folder) / SECRETS_FILE


def _read(folder: Path) -> dict:
    try:
        with open(_path(folder), encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("Couldn't read %s: %s", SECRETS_FILE, e)
        return {}


def _write(folder: Path, values: dict) -> None:
    """Atomically, and readable only by this user where the OS supports it."""
    path = _path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(values, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def get(folder: Path, name: str) -> str:
    """A stored secret, or "" if there is none (or it can't be decrypted on this PC/account)."""
    token = _read(folder).get(name, "")
    if not isinstance(token, str):
        return ""
    try:
        value = unprotect(token)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        log.warning("Couldn't decrypt the stored %s: %s", name, e)
        return ""
    if token.startswith("dpapi:") and value:
        try:  # upgrade a 2.0 secret to the stronger format
            put(folder, name, value)
        except OSError as e:
            log.warning("Couldn't upgrade the stored %s: %s", name, e)
    return value


def put(folder: Path, name: str, value: str | None) -> None:
    """Store (or, with an empty value, remove) a secret."""
    values = _read(folder)
    if value:
        values[name] = protect(value)
    else:
        values.pop(name, None)
    _write(folder, values)


def get_json(folder: Path, name: str) -> dict | None:
    text = get(folder, name)
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def put_json(folder: Path, name: str, value: dict | None) -> None:
    put(folder, name, json.dumps(value) if value else None)
