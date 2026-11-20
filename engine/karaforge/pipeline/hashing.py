"""Content hashing helpers used for cache keys."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's content."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    """Serialise ``value`` deterministically (sorted keys, no whitespace, UTF-8 kept as is)."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    """Return the SHA-256 hex digest of the canonical JSON form of ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class FileHashCache:
    """Remembers file hashes keyed by ``(size, mtime)`` so large media is hashed only once.

    The index lives in a small JSON file inside the project's cache folder.  A stale entry is
    harmless: a changed size or modification time forces a re-hash.
    """

    def __init__(self, index_path: Path) -> None:
        self._index_path = index_path
        self._lock = threading.Lock()
        self._entries: dict[str, list[Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict):
            for key, value in data.items():  # pyright: ignore[reportUnknownVariableType]
                if isinstance(key, str) and isinstance(value, list) and len(value) == 3:  # pyright: ignore[reportUnknownArgumentType]
                    self._entries[key] = value

    def digest(self, path: Path) -> str:
        """Return the content hash of ``path``, reusing a remembered value when possible."""
        stat = path.stat()
        key = str(path.resolve())
        with self._lock:
            self._load()
            entry = self._entries.get(key)
            if entry is not None and entry[0] == stat.st_size and entry[1] == stat.st_mtime_ns:
                return str(entry[2])
        value = sha256_file(path)
        with self._lock:
            self._entries[key] = [stat.st_size, stat.st_mtime_ns, value]
            self._save()
        return value

    def _save(self) -> None:
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._index_path.with_name(self._index_path.name + ".tmp")
            temporary.write_text(json.dumps(self._entries), encoding="utf-8")
            temporary.replace(self._index_path)
        except OSError:
            pass  # the index is only an optimisation
