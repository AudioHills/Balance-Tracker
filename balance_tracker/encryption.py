"""Password-based encryption for the iPhone sync file and exported backups.

AES-256-GCM (from the `cryptography` package) with a key stretched from the passphrase by
PBKDF2-SHA256. GCM also authenticates: a file that was changed, or made with a different
passphrase, fails to open instead of being read as garbage. The format is shared with the
iPhone app (web/crypto.js) and looks like::

    {"app": "BalanceTracker", "encrypted": 1, "kind": "sync" | "backup",
     "kdf": "PBKDF2-SHA256", "iterations": 600000, "salt": "<base64>",
     "cipher": "AES-256-GCM", "iv": "<base64>", "data": "<base64 ciphertext + tag>"}
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import unicodedata
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 600_000  # OWASP's PBKDF2-SHA256 recommendation
MIN_ITERATIONS, MAX_ITERATIONS = 100_000, 5_000_000  # refuse files that are trivially weak or would hang
KINDS = ("sync", "backup")
MIN_PASSPHRASE = 10  # characters, for passphrases the user makes up

# Letters and digits that can't be mistaken for each other when typed on a phone
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class WrongPassword(ValueError):
    """The passphrase doesn't open this file (or the file was tampered with)."""

    def __init__(self):
        super().__init__("Wrong password or passphrase.")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text) -> bytes:
    return base64.b64decode(str(text), validate=True)


def _aad(kind: str) -> bytes:
    return f"BalanceTracker:{kind}:v1".encode()


def suggest_passphrase(groups: int = 5) -> str:
    """A random passphrase like "K7QF-M2XP-9TRA-WD4C-HN3E" (about 99 bits)."""
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(groups))


def passphrase_problem(text: str) -> str:
    """Why a passphrase the user typed isn't good enough, or "" if it's fine."""
    if len(text) < MIN_PASSPHRASE:
        return f"Use at least {MIN_PASSPHRASE} characters."
    if len(set(text)) < 5:
        return "That's too repetitive — mix in more different characters."
    return ""


@dataclass(frozen=True)
class FileKey:
    """A key derived from a passphrase, plus what a file needs to say about how it was derived."""

    key: bytes
    salt: bytes
    iterations: int = ITERATIONS

    @classmethod
    def derive(cls, passphrase: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> FileKey:
        salt = os.urandom(16) if salt is None else salt
        secret = unicodedata.normalize("NFC", passphrase).encode("utf-8")
        return cls(hashlib.pbkdf2_hmac("sha256", secret, salt, iterations, 32), salt, iterations)

    def to_dict(self) -> dict:
        """For storing (protected) in secrets.json."""
        return {"key": _b64(self.key), "salt": _b64(self.salt), "iterations": self.iterations}

    @classmethod
    def from_dict(cls, d: dict) -> FileKey:
        return cls(_unb64(d["key"]), _unb64(d["salt"]), int(d["iterations"]))

    def fits(self, envelope: dict) -> bool:
        """Was `envelope` made with this passphrase-and-salt? (If not, the passphrase is needed.)"""
        try:
            return _unb64(envelope.get("salt", "")) == self.salt and envelope.get("iterations") == self.iterations
        except ValueError:
            return False


def is_encrypted(raw) -> bool:
    """Is this parsed JSON an encrypted Balance Tracker file?"""
    return isinstance(raw, dict) and raw.get("app") == "BalanceTracker" and raw.get("encrypted") == 1


def _check(envelope: dict) -> None:
    it = envelope.get("iterations")
    if (envelope.get("kind") not in KINDS or envelope.get("kdf") != "PBKDF2-SHA256"
            or envelope.get("cipher") != "AES-256-GCM" or not isinstance(it, int) or isinstance(it, bool)
            or not MIN_ITERATIONS <= it <= MAX_ITERATIONS):
        raise ValueError("This encrypted file uses settings this version of Balance Tracker doesn't support.")
    try:
        if len(_unb64(envelope["salt"])) < 16 or len(_unb64(envelope["iv"])) != 12:
            raise ValueError
        _unb64(envelope["data"])
    except (KeyError, ValueError) as e:
        raise ValueError("This encrypted file is damaged.") from e


def seal(text: str, key: FileKey, kind: str) -> str:
    """Encrypt a backup/sync file's JSON text into the encrypted file format."""
    if kind not in KINDS:
        raise ValueError(f"Unknown kind {kind!r}")
    iv = os.urandom(12)
    data = AESGCM(key.key).encrypt(iv, text.encode("utf-8"), _aad(kind))
    return json.dumps({"app": "BalanceTracker", "encrypted": 1, "kind": kind, "kdf": "PBKDF2-SHA256",
                       "iterations": key.iterations, "salt": _b64(key.salt), "cipher": "AES-256-GCM",
                       "iv": _b64(iv), "data": _b64(data)}, indent=1)


def open_with_key(envelope: dict, key: FileKey) -> str:
    """Decrypt with a stored key. Raises WrongPassword if it isn't this file's key."""
    _check(envelope)
    if not key.fits(envelope):
        raise WrongPassword()
    try:
        plain = AESGCM(key.key).decrypt(_unb64(envelope["iv"]), _unb64(envelope["data"]), _aad(envelope["kind"]))
    except InvalidTag as e:
        raise WrongPassword() from e
    return plain.decode("utf-8")


def open_with_passphrase(envelope: dict, passphrase: str) -> tuple[str, FileKey]:
    """Decrypt with a passphrase. Returns the text and the key (so it can be remembered)."""
    _check(envelope)
    key = FileKey.derive(passphrase, _unb64(envelope["salt"]), envelope["iterations"])
    return open_with_key(envelope, key), key
