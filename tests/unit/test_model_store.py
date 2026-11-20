from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from karaforge.errors import JobCancelledError, ModelError
from karaforge.models import registry, store
from karaforge.models.registry import ModelFile, ModelSpec
from karaforge.runtime import CancelToken

PAYLOAD = bytes(range(256)) * 9000  # ~2.3 MB, several download chunks
SMALL = b'{"hello": "world"}'


class _Handler(BaseHTTPRequestHandler):
    """Serves fixed byte strings and honours ``Range: bytes=N-``."""

    files: ClassVar[dict[str, bytes]] = {}
    requests: ClassVar[list[tuple[str, str | None]]] = []
    ignore_range: ClassVar[bool] = False

    def do_GET(self) -> None:
        type(self).requests.append((self.path, self.headers.get("Range")))
        data = type(self).files.get(self.path)
        if data is None:
            self.send_error(404)
            return
        start = 0
        range_header = self.headers.get("Range")
        if range_header and not type(self).ignore_range:
            start = int(range_header.removeprefix("bytes=").split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        """Silence the default request logging."""


@pytest.fixture
def server() -> Iterator[str]:
    _Handler.files = {"/big.bin": PAYLOAD, "/small.json": SMALL, "/dep.txt": b"dependency"}
    _Handler.requests = []
    _Handler.ignore_range = False
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(store.ENV_OFFLINE, raising=False)
    monkeypatch.delenv(store.ENV_ACCEPT_LICENSES, raising=False)
    return tmp_path / "home"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def spec(base: str, **changes: object) -> ModelSpec:
    values: dict[str, object] = {
        "id": "demo",
        "kind": "asr",
        "title": "Demo model",
        "license": "MIT",
        "license_url": "https://example.org/license",
        "homepage": "https://example.org",
        "revision": "r1",
        "commercial_use": True,
        "files": (
            ModelFile(
                path="weights/big.bin",
                url=f"{base}/big.bin",
                size=len(PAYLOAD),
                sha256=sha(PAYLOAD),
            ),
            ModelFile(
                path="small.json", url=f"{base}/small.json", size=len(SMALL), sha256=sha(SMALL)
            ),
        ),
    }
    values.update(changes)
    return ModelSpec.model_validate(values)


def test_download_writes_verified_files_and_reports_progress(
    server: str, isolated_home: Path
) -> None:
    model = spec(server)
    assert not store.is_installed(model)
    fractions: list[float] = []
    directory = store.download(model, progress=lambda fraction, _label: fractions.append(fraction))
    assert directory == isolated_home / "models" / "demo"
    assert (directory / "weights" / "big.bin").read_bytes() == PAYLOAD
    assert (directory / "small.json").read_bytes() == SMALL
    assert store.is_installed(model)
    assert store.verify(model) == []
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    assert not list(directory.rglob("*.part"))


def test_second_download_does_nothing(server: str) -> None:
    model = spec(server)
    store.download(model)
    before = len(_Handler.requests)
    store.download(model)
    assert len(_Handler.requests) == before


def test_interrupted_download_is_resumed_with_a_range_request(
    server: str, isolated_home: Path
) -> None:
    model = spec(server)
    partial = isolated_home / "models" / "demo" / "weights" / "big.bin.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(PAYLOAD[:1_000_000])
    store.download(model)
    assert ("/big.bin", "bytes=1000000-") in _Handler.requests
    assert (partial.parent / "big.bin").read_bytes() == PAYLOAD


def test_server_without_range_support_restarts_the_file(server: str, isolated_home: Path) -> None:
    _Handler.ignore_range = True
    model = spec(server)
    partial = isolated_home / "models" / "demo" / "weights" / "big.bin.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"garbage that must not survive")
    store.download(model)
    assert (partial.parent / "big.bin").read_bytes() == PAYLOAD


def test_checksum_mismatch_deletes_the_download(server: str, isolated_home: Path) -> None:
    bad = ModelFile(path="small.json", url=f"{server}/small.json", size=len(SMALL), sha256="0" * 64)
    model = spec(server, files=(bad,))
    with pytest.raises(ModelError) as info:
        store.download(model)
    assert "Checksum" in info.value.message_en
    directory = isolated_home / "models" / "demo"
    assert not (directory / "small.json").exists()
    assert not (directory / "small.json.part").exists()
    assert not store.is_installed(model)


def test_http_error_is_reported(server: str) -> None:
    missing = ModelFile(path="x.bin", url=f"{server}/nope.bin", size=10, sha256="0" * 64)
    with pytest.raises(ModelError) as info:
        store.download(spec(server, files=(missing,)))
    assert "404" in info.value.message_en


def test_unreachable_server_is_reported_with_a_hint() -> None:
    dead = ModelFile(path="x.bin", url="http://127.0.0.1:9/x.bin", size=10, sha256="0" * 64)
    with pytest.raises(ModelError) as info:
        store.download(spec("http://127.0.0.1:9", files=(dead,)))
    assert info.value.hint_zh is not None
    assert "續傳" in info.value.hint_zh


def test_offline_mode_refuses_to_download(server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(store.ENV_OFFLINE, "1")
    assert store.offline()
    with pytest.raises(ModelError) as info:
        store.download(spec(server))
    assert "kf models download demo" in (info.value.hint_en or "")
    assert _Handler.requests == []


def test_non_commercial_model_needs_explicit_acceptance(
    server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = spec(server, commercial_use=False, license="CC-BY-NC-4.0")
    assert not store.license_accepted(model)
    with pytest.raises(ModelError) as info:
        store.download(model)
    assert "--accept-license" in (info.value.hint_en or "")
    assert _Handler.requests == []
    monkeypatch.setenv(store.ENV_ACCEPT_LICENSES, "other, demo")
    assert store.license_accepted(model)
    store.download(model)
    assert store.is_installed(model)


def test_verify_reports_missing_wrong_size_and_corrupt_files(server: str) -> None:
    model = spec(server)
    assert store.verify(model) == ["weights/big.bin: missing", "small.json: missing"]
    directory = store.download(model)
    (directory / "small.json").write_bytes(b"x" * len(SMALL))
    (directory / "weights" / "big.bin").write_bytes(PAYLOAD[:-1])
    problems = store.verify(model)
    assert problems[0].startswith("weights/big.bin: size")
    assert problems[1] == "small.json: checksum mismatch"
    assert not store.is_installed(model)


def test_cancelling_keeps_the_partial_file_for_resuming(server: str, isolated_home: Path) -> None:
    token = CancelToken()

    def cancel_midway(fraction: float, _label: str) -> None:
        if fraction > 0.3:
            token.cancel()

    with pytest.raises(JobCancelledError):
        store.download(spec(server), progress=cancel_midway, cancel=token)
    partial = isolated_home / "models" / "demo" / "weights" / "big.bin.part"
    assert partial.is_file()
    assert 0 < partial.stat().st_size < len(PAYLOAD)
    assert not (partial.parent / "big.bin").exists()


def test_required_models_are_downloaded_first_and_shared_folders_work(
    server: str, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dependency = spec(
        server,
        id="dep",
        directory="shared",
        files=(
            ModelFile(path="dep.txt", url=f"{server}/dep.txt", size=10, sha256=sha(b"dependency")),
        ),
    )
    main = spec(server, id="main", directory="shared", requires=("dep",))
    monkeypatch.setattr(registry, "load_registry", lambda: {"dep": dependency, "main": main})
    assert store.ensure("main") == isolated_home / "models" / "shared"
    assert (isolated_home / "models" / "shared" / "dep.txt").read_bytes() == b"dependency"
    assert store.is_installed(main)
    (isolated_home / "models" / "shared" / "dep.txt").unlink()
    assert not store.is_installed(main)


def test_ensure_unknown_model_raises() -> None:
    with pytest.raises(ModelError):
        store.ensure("no-such-model")
