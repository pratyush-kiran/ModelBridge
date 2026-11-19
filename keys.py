"""Persistent local API keys.

Requests are checked against SHA-256 fingerprints. So that a key can be viewed
and copied again later, the key itself is also kept, encrypted for the current
Windows user with DPAPI (other platforms store it base64-encoded only).
"""

from datetime import datetime
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
from threading import Lock


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    if os.name != "nt":
        return data
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


def seal(token):
    return base64.b64encode(_dpapi(token.encode(), True)).decode()


def unseal(secret):
    return _dpapi(base64.b64decode(secret), False).decode()


class KeyStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(
            os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")
        ) / "ModelBridge" / "keys.json"
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
                  "secret": seal(token)}
        with self.lock:
            self.commit({**self.keys, digest: record})
        return token

    def reveal(self, digest):
        """Return the full key, or None for keys saved before keys were kept."""
        secret = self.keys.get(digest, {}).get("secret")
        if not secret:
            return None
        token = unseal(secret)
        return token if hashlib.sha256(token.encode()).hexdigest() == digest else None

    def revoke(self, digest):
        with self.lock:
            self.commit({key: record for key, record in self.keys.items() if key != digest})
