"""Downloading, locating and verifying model weights under ``$KARAFORGE_HOME/models``.

Downloads are resumable (HTTP ``Range``), written to ``<name>.part`` first, verified against
the SHA-256 recorded in the registry and only then moved into place, so an interrupted or
corrupted download can never be mistaken for a complete model.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import httpx

from karaforge import paths
from karaforge.errors import ModelError
from karaforge.models.registry import ModelFile, ModelSpec, get_model
from karaforge.runtime import CancelToken, ProgressFn, null_progress

ENV_OFFLINE = "KARAFORGE_OFFLINE"
ENV_ACCEPT_LICENSES = "KARAFORGE_ACCEPT_LICENSES"
_CHUNK = 1 << 20
_TIMEOUT = httpx.Timeout(30.0, read=120.0)


def model_dir(spec: ModelSpec) -> Path:
    """Directory that holds (or will hold) the files of ``spec``."""
    return paths.models_dir() / spec.folder


def file_path(spec: ModelSpec, file: ModelFile) -> Path:
    """Absolute location of one file of a model."""
    return model_dir(spec) / Path(*file.path.split("/"))


def is_installed(spec: ModelSpec) -> bool:
    """Whether every file of ``spec`` and of the models it requires is present.

    Only existence and size are checked; use :func:`verify` for a checksum comparison.
    """
    for file in spec.files:
        path = file_path(spec, file)
        if not path.is_file() or path.stat().st_size != file.size:
            return False
    return all(is_installed(get_model(other)) for other in spec.requires)


def sha256_of(path: Path) -> str:
    """SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify(spec: ModelSpec) -> list[str]:
    """Check the files of ``spec`` against the registry.

    Returns:
        Human-readable problems (empty when everything matches).
    """
    problems: list[str] = []
    for file in spec.files:
        path = file_path(spec, file)
        if not path.is_file():
            problems.append(f"{file.path}: missing")
        elif path.stat().st_size != file.size:
            problems.append(f"{file.path}: size {path.stat().st_size}, expected {file.size}")
        elif sha256_of(path) != file.sha256:
            problems.append(f"{file.path}: checksum mismatch")
    return problems


def offline() -> bool:
    """Whether downloads are disabled (``KARAFORGE_OFFLINE=1``)."""
    return os.environ.get(ENV_OFFLINE, "").strip().lower() in {"1", "true", "yes", "on"}


def license_accepted(spec: ModelSpec) -> bool:
    """Whether the user may download ``spec``.

    Models whose licence forbids commercial use are only downloaded after the user opted in,
    either with ``kf models download <id> --accept-license`` or by listing the model id in
    ``KARAFORGE_ACCEPT_LICENSES`` (comma separated).
    """
    if spec.commercial_use:
        return True
    accepted = {item.strip() for item in os.environ.get(ENV_ACCEPT_LICENSES, "").split(",")}
    return spec.id in accepted or "*" in accepted


def _download_file(
    client: httpx.Client,
    file: ModelFile,
    target: Path,
    progress: ProgressFn,
    cancel: CancelToken | None,
    done_before: int,
    total: int,
    label: str,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    offset = partial.stat().st_size if partial.is_file() else 0
    if offset > file.size:
        partial.unlink()
        offset = 0
    if offset < file.size or file.size == 0:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with client.stream("GET", file.url, headers=headers) as response:
                if offset and response.status_code == 200:
                    offset = 0  # the server ignored the range: start over
                elif response.status_code not in (200, 206):
                    raise ModelError(
                        f"下載模型檔失敗（HTTP {response.status_code}）：{file.path}",
                        f"Model download failed (HTTP {response.status_code}): {file.path}",
                        detail=file.url,
                    )
                with partial.open("ab" if offset else "wb") as handle:
                    received = offset
                    for chunk in response.iter_bytes(_CHUNK):
                        if cancel is not None:
                            cancel.raise_if_cancelled()
                        handle.write(chunk)
                        received += len(chunk)
                        if total:
                            progress(min(1.0, (done_before + received) / total), label)
        except httpx.HTTPError as exc:
            raise ModelError(
                f"下載模型檔時連線失敗：{file.path}",
                f"Network error while downloading {file.path}",
                hint_zh="請檢查網路後重試；已下載的部分會保留，下次會從中斷處續傳。",
                hint_en="Check your connection and retry; the partial download is kept "
                "and will be resumed.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
    actual = sha256_of(partial)
    if actual != file.sha256:
        partial.unlink(missing_ok=True)
        raise ModelError(
            f"模型檔的檢查碼不符，已刪除：{file.path}",
            f"Checksum mismatch for {file.path}; the file was deleted.",
            hint_zh="請重新下載。如果問題持續，上游檔案可能已經變動，請回報。",
            hint_en="Please download again. If this persists the upstream file may have changed.",
            detail=f"expected {file.sha256}, got {actual}",
        )
    partial.replace(target)


def download(
    spec: ModelSpec,
    *,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """Download the missing files of ``spec`` (and of the models it requires).

    Returns:
        The model directory.

    Raises:
        ModelError: When offline, when the licence was not accepted, on network errors and
            on checksum mismatches.
    """
    for other in spec.requires:
        other_spec = get_model(other)
        if not is_installed(other_spec):
            download(other_spec, progress=progress, cancel=cancel, client=client)
    missing = [
        file
        for file in spec.files
        if not file_path(spec, file).is_file() or file_path(spec, file).stat().st_size != file.size
    ]
    if not missing:
        return model_dir(spec)
    if offline():
        raise ModelError(
            f"缺少模型「{spec.id}」，而且目前是離線模式（KARAFORGE_OFFLINE）。",
            f"Model '{spec.id}' is missing and offline mode (KARAFORGE_OFFLINE) is on.",
            hint_zh=f"連上網路後執行：kf models download {spec.id}",
            hint_en=f"Go online and run: kf models download {spec.id}",
        )
    if not license_accepted(spec):
        raise ModelError(
            f"模型「{spec.id}」的授權是 {spec.license}，不允許商業使用，需要你明確同意後才會下載。",
            f"Model '{spec.id}' is licensed {spec.license} (no commercial use); "
            "it is only downloaded after you accept that.",
            hint_zh=f"閱讀授權（{spec.license_url}）後執行："
            f"kf models download {spec.id} --accept-license",
            hint_en=f"Read the licence ({spec.license_url}), then run: "
            f"kf models download {spec.id} --accept-license",
        )
    total = sum(file.size for file in missing)
    label = spec.id
    owned = client is None
    session = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        done = 0
        for file in missing:
            _download_file(
                session, file, file_path(spec, file), progress, cancel, done, total, label
            )
            done += file.size
    finally:
        if owned:
            session.close()
    progress(1.0, label)
    return model_dir(spec)


def ensure(
    model_id: str,
    *,
    progress: ProgressFn = null_progress,
    cancel: CancelToken | None = None,
) -> Path:
    """Return the directory of an installed model, downloading it first when necessary."""
    spec = get_model(model_id)
    if is_installed(spec):
        return model_dir(spec)
    return download(spec, progress=progress, cancel=cancel)
