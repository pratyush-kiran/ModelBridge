"""Persistent local API keys.

Requests are checked against SHA-256 fingerprints. So that a key can be viewed
and copied again later, the key itself is also kept: encrypted with DPAPI on
Windows, in the login Keychain on macOS. Elsewhere only the fingerprint is kept.
"""

from datetime import datetime
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from threading import Lock

import macos

MACOS = sys.platform == "darwin"


def data_directory():
    if MACOS:
        return Path.home() / "Library" / "Application Support" / "ModelBridge"
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "ModelBridge"


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    source = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                          ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    call = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not call(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):
        raise OSError("Windows could not protect the key.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


def seal(digest, token):
    if os.name == "nt":
        return base64.b64encode(_dpapi(token.encode(), True)).decode()
    if MACOS:
        macos.keychain_save(digest, token)
        return "keychain"
    return ""


def unseal(digest, secret):
    if os.name == "nt":
        return _dpapi(base64.b64decode(secret), False).decode()
    return macos.keychain_read(digest)


class KeyStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / "keys.json"
        self.lock = Lock()
        if self.path.exists():
            self.keys = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.keys, dict) or any(
                not isinstance(record, dict) or
                not all(isinstance(record.get(field), str) for field in ("name", "suffix", "date"))
                for record in self.keys.values()
            ):
                raise ValueError("Invalid key store.")
        else:
            self.keys = {}

    def contains(self, digest):
        with self.lock:
            return digest in self.keys

    def commit(self, keys):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, filename = tempfile.mkstemp(dir=self.path.parent, prefix=".keys-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(keys, stream, indent=2, ensure_ascii=False)
            os.replace(filename, self.path)
        finally:
            Path(filename).unlink(missing_ok=True)
        self.keys = keys

    def create(self, name):
        token = "mb_" + secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        record = {"name": name, "suffix": token[-6:], "date": datetime.now().strftime("%d %b %Y"),
                  "secret": seal(digest, token)}
        with self.lock:
            self.commit({**self.keys, digest: record})
        return token

    def reveal(self, digest):
        """Return the full key, or None for keys saved before keys were kept."""
        secret = self.keys.get(digest, {}).get("secret")
        if not secret:
            return None
        token = unseal(digest, secret)
        return token if hashlib.sha256(token.encode()).hexdigest() == digest else None

    def revoke(self, digest):
        with self.lock:
            record = self.keys.get(digest, {})
            self.commit({key: value for key, value in self.keys.items() if key != digest})
        if MACOS and record.get("secret"):
            try:
                macos.keychain_delete(digest)
            except (OSError, subprocess.SubprocessError):
                pass  # Already revoked; a leftover Keychain item grants nothing.
