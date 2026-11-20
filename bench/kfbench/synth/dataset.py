"""The synthetic benchmark dataset: which songs exist, where they live, how to build them.

Songs are identified by ``(language, seed)``.  Two disjoint seed ranges are used:

``dev``
    Seeds 2000–2003 per language.  Everything that has a tunable parameter — aligner bias
    correction, snapping distance, thresholds — is tuned on these songs only.
``test``
    Seeds 1000–1009 per language (ten songs each, as the specification asks).  Used only to
    produce the reported numbers.

Generated files live outside version control (``bench/_data`` in a checkout); they can be
recreated at any time, and ``manifest.json`` records a hash of every file so that a rebuilt
dataset can be compared with the one behind a published report.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from karaforge import paths
from karaforge.pipeline.hashing import sha256_file
from kfbench.synth.song import GENERATOR_VERSION, SNR_LEVELS_DB, plan_song, render_song
from kfbench.synth.tts import ClipCache, KokoroTTS, TTSBackend

ENV_DATA = "KARAFORGE_BENCH_DATA"
LANGUAGES: tuple[str, ...] = ("zh", "en", "mixed")
SPLITS: dict[str, tuple[int, ...]] = {
    "test": tuple(range(1000, 1010)),
    "dev": tuple(range(2000, 2004)),
    "smoke": (2000,),
}
PROJECT_LANGUAGE = {"zh": "zh-TW", "en": "en", "mixed": "zh-TW"}
"""Project language to use for each benchmark language."""


@dataclass(frozen=True)
class SongEntry:
    """A generated song on disk."""

    language: str
    seed: int
    directory: Path

    @property
    def song_id(self) -> str:
        """Identifier such as ``zh-1003``."""
        return f"{self.language}-{self.seed:04d}"

    @property
    def lyrics(self) -> Path:
        """The lyrics file in KaraForge's ``.txt`` format."""
        return self.directory / "lyrics.txt"

    @property
    def truth(self) -> Path:
        """Ground-truth timing."""
        return self.directory / "truth.json"

    def mix(self, snr_db: int) -> Path:
        """The mix at the given vocal-to-accompaniment ratio."""
        return self.directory / f"mix_snr{snr_db:02d}.wav"

    @property
    def is_complete(self) -> bool:
        """Whether every file of the song exists and was made by the current generator."""
        if not self.truth.is_file() or not self.lyrics.is_file():
            return False
        if not all(self.mix(snr).is_file() for snr in SNR_LEVELS_DB):
            return False
        try:
            version = json.loads(self.truth.read_text(encoding="utf-8")).get("generator_version")
        except (OSError, json.JSONDecodeError):
            return False
        return version == GENERATOR_VERSION


def data_root() -> Path:
    """Folder that holds generated benchmark data.

    ``KARAFORGE_BENCH_DATA`` wins; in a source checkout it is ``bench/_data``; otherwise a
    folder under ``KARAFORGE_HOME``.
    """
    override = os.environ.get(ENV_DATA)
    if override:
        return Path(override).expanduser()
    root = paths.repo_root()
    if root is not None:
        return root / "bench" / "_data"
    return paths.home_dir() / "bench" / "data"


def dataset_dir() -> Path:
    """Folder of the dataset made by the current generator version."""
    return data_root() / "synthetic" / f"v{GENERATOR_VERSION}"


def song_entry(language: str, seed: int) -> SongEntry:
    """Where a song is (or will be) stored."""
    return SongEntry(language, seed, dataset_dir() / f"{language}-{seed:04d}")


def split_entries(split: str, languages: Sequence[str] = LANGUAGES) -> list[SongEntry]:
    """The songs of a split, without generating anything."""
    return [song_entry(language, seed) for language in languages for seed in SPLITS[split]]


def default_tts() -> TTSBackend:
    """The TTS engine the benchmark is defined with."""
    return KokoroTTS()


def ensure_songs(
    entries: Sequence[SongEntry],
    *,
    backend: TTSBackend | None = None,
    on_song: Callable[[SongEntry, bool], None] | None = None,
) -> list[SongEntry]:
    """Generate the songs that are missing and refresh the manifest.

    Args:
        entries: Songs that must exist.
        backend: TTS engine; created on first need when omitted.
        on_song: Called after each song with ``(entry, was_generated)``.

    Returns:
        ``entries``, all of them now complete.
    """
    cache: ClipCache | None = None
    generated = False
    for entry in entries:
        made = False
        if not entry.is_complete:
            if cache is None:
                cache = ClipCache(
                    backend or default_tts(), paths.home_dir() / "bench" / "tts-cache"
                )
            render_song(plan_song(entry.language, entry.seed), cache, entry.directory)
            made = generated = True
        if on_song is not None:
            on_song(entry, made)
    if generated or not (dataset_dir() / "manifest.json").is_file():
        write_manifest()
    return list(entries)


def write_manifest() -> Path:
    """Record the SHA-256 of every generated file in ``manifest.json``."""
    root = dataset_dir()
    songs: dict[str, dict[str, str]] = {}
    if root.is_dir():
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            files = sorted(path for path in directory.iterdir() if path.is_file())
            songs[directory.name] = {path.name: sha256_file(path) for path in files}
    path = root / "manifest.json"
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"generator_version": GENERATOR_VERSION, "songs": songs}, indent=1),
        encoding="utf-8",
    )
    return path
