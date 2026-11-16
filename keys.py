"""Persistent local API keys. Only SHA-256 fingerprints are kept on disk."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
from threading import Lock


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
        record = {"name": name, "suffix": token[-6:], "date": datetime.now().strftime("%d %b %Y")}
        with self.lock:
            self.commit({**self.keys, digest: record})
        return token

    def revoke(self, digest):
        with self.lock:
            self.commit({key: record for key, record in self.keys.items() if key != digest})
