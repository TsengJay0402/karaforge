from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from karaforge.pipeline import hashing
from karaforge.pipeline.hashing import FileHashCache, canonical_json, sha256_file, sha256_json


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    data = b"hello karaforge" * 1000
    path = tmp_path / "data.bin"
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_sha256_file_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    assert sha256_file(path) == hashlib.sha256(b"").hexdigest()


def test_sha256_file_larger_than_chunk_size(tmp_path: Path) -> None:
    data = bytes(range(256)) * (2**20 + 17)
    path = tmp_path / "big.bin"
    path.write_bytes(data)
    assert len(data) > 2**20
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_canonical_json_sorts_keys_and_has_no_whitespace() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_json({"x": [1, 2], "y": {"k": True}}) == '{"x":[1,2],"y":{"k":true}}'


def test_canonical_json_keeps_chinese_unescaped() -> None:
    assert canonical_json({"k": "中文"}) == '{"k":"中文"}'


def test_sha256_json_is_order_independent() -> None:
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})
    assert sha256_json({"a": 1}) != sha256_json({"a": 2})


def test_digest_returns_correct_hash(tmp_path: Path) -> None:
    path = tmp_path / "audio.wav"
    payload = b"\x01\x02\x03" * 4096
    path.write_bytes(payload)
    cache = FileHashCache(tmp_path / "index.json")
    assert cache.digest(path) == hashlib.sha256(payload).hexdigest()


def test_digest_second_call_does_not_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "audio.wav"
    path.write_bytes(b"stable content")
    calls: list[Path] = []
    original = hashing.sha256_file

    def counting(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(hashing, "sha256_file", counting)
    cache = FileHashCache(tmp_path / "index.json")
    first = cache.digest(path)
    second = cache.digest(path)
    assert first == second
    assert len(calls) == 1


def test_digest_recomputes_when_content_and_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "audio.wav"
    path.write_bytes(b"first version")
    original = hashing.sha256_file
    calls: list[Path] = []

    def counting(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(hashing, "sha256_file", counting)
    cache = FileHashCache(tmp_path / "index.json")
    first = cache.digest(path)

    path.write_bytes(b"first version!")  # different size ...
    future = 2_000_000_000_000_000_000
    os.utime(path, ns=(future, future))  # ... and a very different mtime
    second = cache.digest(path)

    assert len(calls) == 2
    assert second == hashlib.sha256(b"first version!").hexdigest()
    assert second != first


def test_digest_recomputes_when_only_mtime_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "audio.wav"
    path.write_bytes(b"same size A")
    original = hashing.sha256_file
    calls: list[Path] = []

    def counting(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(hashing, "sha256_file", counting)
    cache = FileHashCache(tmp_path / "index.json")
    cache.digest(path)

    os.utime(path, ns=(2_000_000_000_000_000_000, 2_000_000_000_000_000_000))
    cache.digest(path)
    assert len(calls) == 2


def test_digest_survives_corrupt_index_file(tmp_path: Path) -> None:
    path = tmp_path / "audio.wav"
    path.write_bytes(b"content")
    index = tmp_path / "index.json"
    index.write_text("{not valid json", encoding="utf-8")
    cache = FileHashCache(index)
    assert cache.digest(path) == hashlib.sha256(b"content").hexdigest()


def test_new_cache_reuses_index_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "audio.wav"
    path.write_bytes(b"cached content")
    index = tmp_path / "index.json"
    expected = hashlib.sha256(b"cached content").hexdigest()

    first = FileHashCache(index)
    assert first.digest(path) == expected
    assert index.is_file()

    def fail(path: Path) -> str:
        raise AssertionError("sha256_file must not be called again")

    monkeypatch.setattr(hashing, "sha256_file", fail)
    second = FileHashCache(index)
    assert second.digest(path) == expected


def test_index_file_is_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "audio.wav"
    path.write_bytes(b"content")
    index = tmp_path / "nested" / "index.json"
    cache = FileHashCache(index)
    cache.digest(path)
    data = json.loads(index.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert str(path.resolve()) in data
