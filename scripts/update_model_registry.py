"""Regenerate ``engine/karaforge/models/registry.json``.

For every model listed in ``SOURCES`` this script pins the upstream revision, lists the files
and records their sizes and SHA-256 checksums:

* Hugging Face repositories: the commit hash of ``main`` is resolved once and every URL points
  at that commit.  Checksums of LFS files come from the Hub's metadata; small non-LFS files
  are downloaded and hashed.
* Plain URLs (GitHub release assets, raw files pinned to a commit): downloaded and hashed.

Run it from the repository root whenever a model is added or bumped::

    uv run python scripts/update_model_registry.py

Existing entries are reused when their revision is unchanged, so re-running is cheap.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REGISTRY = (
    Path(__file__).resolve().parent.parent / "engine" / "karaforge" / "models" / "registry.json"
)
HF_API = "https://huggingface.co/api/models"
SKIP_FILES = {".gitattributes", "README.md"}
SKIP_SUFFIXES = (".md", ".png", ".jpg", ".msgpack", ".h5", ".ot", ".safetensors.index.json")

UVR_DATA_REPO = "TRvlvr/application_data"
UVR_MODEL_URL = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models"
UVR_HOME = "https://github.com/Anjok07/ultimatevocalremovergui"
UVR_NOTE_ZH = "UVR 專案訓練的模型;使用時請依 UVR 的要求標示出處。"
UVR_NOTE_EN = "Trained by the UVR project; please credit UVR when you use it."


@dataclass
class HFSource:
    """A Hugging Face model repository."""

    id: str
    kind: str
    title: str
    repo: str
    license: str
    license_url: str
    commercial_use: bool = True
    include: tuple[str, ...] = ()
    """When set, only these paths are taken."""
    exclude: tuple[str, ...] = ()
    note_zh: str = ""
    note_en: str = ""
    requires: tuple[str, ...] = ()


@dataclass
class URLSource:
    """Files addressed by plain, immutable URLs."""

    id: str
    kind: str
    title: str
    license: str
    license_url: str
    homepage: str
    revision: str
    files: dict[str, str] = field(default_factory=dict)
    commercial_use: bool = True
    directory: str | None = None
    note_zh: str = ""
    note_en: str = ""
    requires: tuple[str, ...] = ()


def sources(client: httpx.Client) -> list[HFSource | URLSource]:
    """The models KaraForge knows about."""
    uvr_commit = client.get(f"https://api.github.com/repos/{UVR_DATA_REPO}/commits/main").json()[
        "sha"
    ]
    uvr_raw = f"https://raw.githubusercontent.com/{UVR_DATA_REPO}/{uvr_commit}"
    whisper_license = "https://github.com/openai/whisper/blob/main/LICENSE"
    return [
        HFSource(
            id="whisper-tiny",
            kind="asr",
            title="Whisper tiny (CTranslate2)",
            repo="Systran/faster-whisper-tiny",
            license="MIT",
            license_url=whisper_license,
        ),
        HFSource(
            id="whisper-base",
            kind="asr",
            title="Whisper base (CTranslate2)",
            repo="Systran/faster-whisper-base",
            license="MIT",
            license_url=whisper_license,
        ),
        HFSource(
            id="whisper-small",
            kind="asr",
            title="Whisper small (CTranslate2)",
            repo="Systran/faster-whisper-small",
            license="MIT",
            license_url=whisper_license,
        ),
        HFSource(
            id="whisper-medium",
            kind="asr",
            title="Whisper medium (CTranslate2)",
            repo="Systran/faster-whisper-medium",
            license="MIT",
            license_url=whisper_license,
        ),
        HFSource(
            id="whisper-large-v3-turbo",
            kind="asr",
            title="Whisper large-v3-turbo (CTranslate2)",
            repo="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
            license="MIT",
            license_url=whisper_license,
        ),
        HFSource(
            id="wav2vec2-zh",
            kind="aligner",
            title="wav2vec2 XLSR-53 Chinese (character CTC)",
            repo="jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
            license="Apache-2.0",
            license_url="https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
            include=(
                "config.json",
                "preprocessor_config.json",
                "special_tokens_map.json",
                "vocab.json",
                "pytorch_model.bin",
            ),
            note_zh="以 Common Voice 中文訓練的字元層級 CTC 模型,用於中文強制對齊。",
            note_en="Character-level CTC model trained on Common Voice zh-CN; used for "
            "Chinese forced alignment.",
        ),
        HFSource(
            id="wav2vec2-en",
            kind="aligner",
            title="wav2vec2 base 960h English (letter CTC)",
            repo="facebook/wav2vec2-base-960h",
            license="Apache-2.0",
            license_url="https://huggingface.co/facebook/wav2vec2-base-960h",
            include=(
                "config.json",
                "preprocessor_config.json",
                "special_tokens_map.json",
                "tokenizer_config.json",
                "vocab.json",
                "model.safetensors",
            ),
            note_zh="以 LibriSpeech 訓練的英文字母層級 CTC 模型,用於英文強制對齊。",
            note_en="Letter-level CTC model trained on LibriSpeech; used for English "
            "forced alignment.",
        ),
        HFSource(
            id="mms-fa",
            kind="aligner",
            title="MMS-300M forced aligner (romanised, 1100+ languages)",
            repo="MahmoudAshraf/mms-300m-1130-forced-aligner",
            license="CC-BY-NC-4.0",
            license_url="https://creativecommons.org/licenses/by-nc/4.0/",
            commercial_use=False,
            include=(
                "config.json",
                "preprocessor_config.json",
                "special_tokens_map.json",
                "tokenizer_config.json",
                "vocab.json",
                "model.safetensors",
            ),
            note_zh="Meta MMS 的多語強制對齊模型(羅馬拼音輸入)。授權為 CC-BY-NC:不可商業使用,"
            "必須由使用者明確同意後才會下載。",
            note_en="Meta's multilingual MMS alignment model (romanised input). CC-BY-NC: "
            "no commercial use; downloaded only after explicit acceptance.",
        ),
        HFSource(
            id="qwen3-forced-aligner",
            kind="aligner",
            title="Qwen3-ForcedAligner-0.6B",
            repo="Qwen/Qwen3-ForcedAligner-0.6B",
            license="Apache-2.0",
            license_url="https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B",
            include=(
                "chat_template.json",
                "config.json",
                "generation_config.json",
                "merges.txt",
                "preprocessor_config.json",
                "tokenizer_config.json",
                "vocab.json",
                "model.safetensors",
            ),
            note_zh="阿里巴巴 Qwen 團隊的強制對齊模型(11 種語言)。需要另外安裝 qwen-asr 套件"
            "(uv sync --extra qwen)。",
            note_en="Forced-alignment model by Alibaba's Qwen team (11 languages). Needs the "
            "optional qwen-asr package (uv sync --extra qwen).",
        ),
        URLSource(
            id="uvr-metadata",
            kind="support",
            title="UVR model parameter tables",
            license="MIT",
            license_url=f"{UVR_HOME}/blob/master/LICENSE",
            homepage=f"https://github.com/{UVR_DATA_REPO}",
            revision=uvr_commit,
            directory="uvr",
            files={
                "download_checks.json": f"{uvr_raw}/filelists/download_checks.json",
                "mdx_model_data.json": f"{uvr_raw}/mdx_model_data/model_data_new.json",
                "vr_model_data.json": f"{uvr_raw}/vr_model_data/model_data_new.json",
            },
            note_zh="audio-separator 讀取模型參數用的對照表。",
            note_en="Lookup tables that audio-separator needs to configure UVR models.",
        ),
        URLSource(
            id="uvr-mdxnet-kara-2",
            kind="separator",
            title="UVR MDX-Net Karaoke 2",
            license="MIT",
            license_url=f"{UVR_HOME}/blob/master/LICENSE",
            homepage=UVR_HOME,
            revision="all_public_uvr_models",
            directory="uvr",
            requires=("uvr-metadata",),
            files={"UVR_MDXNET_KARA_2.onnx": f"{UVR_MODEL_URL}/UVR_MDXNET_KARA_2.onnx"},
            note_zh=UVR_NOTE_ZH + "伴唱型:和聲保留在伴奏裡。",
            note_en=UVR_NOTE_EN + " Karaoke type: backing vocals stay in the accompaniment.",
        ),
    ]


def sha256_of_url(client: httpx.Client, url: str) -> tuple[int, str]:
    """Download ``url`` and return ``(size, sha256)``."""
    digest = hashlib.sha256()
    size = 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def build_hf(
    client: httpx.Client, source: HFSource, previous: dict[str, Any] | None
) -> dict[str, Any]:
    """Build the registry entry of a Hugging Face repository."""
    revision = client.get(f"{HF_API}/{source.repo}").json()["sha"]
    if previous is not None and previous.get("revision") == revision:
        files = previous["files"]
    else:
        tree = client.get(
            f"{HF_API}/{source.repo}/tree/{revision}", params={"recursive": "true"}
        ).json()
        files = []
        for item in tree:
            path = item["path"]
            if item["type"] != "file" or path in SKIP_FILES or path.endswith(SKIP_SUFFIXES):
                continue
            if source.include and path not in source.include:
                continue
            if path in source.exclude:
                continue
            url = f"https://huggingface.co/{source.repo}/resolve/{revision}/{path}"
            if "lfs" in item:
                size, checksum = item["lfs"]["size"], item["lfs"]["oid"]
            else:
                size, checksum = sha256_of_url(client, url)
            files.append({"path": path, "url": url, "size": size, "sha256": checksum})
            print(f"  {path}  {size:,} bytes", file=sys.stderr)
    return {
        "id": source.id,
        "kind": source.kind,
        "title": source.title,
        "license": source.license,
        "license_url": source.license_url,
        "homepage": f"https://huggingface.co/{source.repo}",
        "revision": revision,
        "commercial_use": source.commercial_use,
        "directory": None,
        "requires": list(source.requires),
        "note_zh": source.note_zh,
        "note_en": source.note_en,
        "files": files,
    }


def build_url(
    client: httpx.Client, source: URLSource, previous: dict[str, Any] | None
) -> dict[str, Any]:
    """Build the registry entry of a set of plain URLs."""
    known = {file["url"]: file for file in previous["files"]} if previous else {}
    files = []
    for path, url in source.files.items():
        if url in known:
            files.append(known[url])
            continue
        size, checksum = sha256_of_url(client, url)
        files.append({"path": path, "url": url, "size": size, "sha256": checksum})
        print(f"  {path}  {size:,} bytes", file=sys.stderr)
    return {
        "id": source.id,
        "kind": source.kind,
        "title": source.title,
        "license": source.license,
        "license_url": source.license_url,
        "homepage": source.homepage,
        "revision": source.revision,
        "commercial_use": source.commercial_use,
        "directory": source.directory,
        "requires": list(source.requires),
        "note_zh": source.note_zh,
        "note_en": source.note_en,
        "files": files,
    }


def main() -> None:
    """Rebuild the registry file."""
    previous: dict[str, Any] = {}
    if REGISTRY.is_file():
        previous = {
            entry["id"]: entry
            for entry in json.loads(REGISTRY.read_text(encoding="utf-8"))["models"]
        }
    entries = []
    with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as client:
        for source in sources(client):
            print(source.id, file=sys.stderr)
            if isinstance(source, HFSource):
                entries.append(build_hf(client, source, previous.get(source.id)))
            else:
                entries.append(build_url(client, source, previous.get(source.id)))
    payload = {
        "generated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d"),
        "models": entries,
    }
    REGISTRY.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {REGISTRY} ({len(entries)} models)", file=sys.stderr)


if __name__ == "__main__":
    main()
