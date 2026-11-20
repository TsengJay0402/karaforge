"""Benchmark suites: the synthetic dataset and the user's own real songs."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from karaforge import paths
from karaforge.errors import KaraForgeError
from karaforge.project import ProjectStore
from karaforge.project.create import MEDIA_EXTENSIONS
from kfbench.runner import BenchItem
from kfbench.synth.dataset import (
    LANGUAGES,
    PROJECT_LANGUAGE,
    SPLITS,
    SongEntry,
    ensure_songs,
    song_entry,
)
from kfbench.synth.song import SNR_LEVELS_DB


class BenchDataError(KaraForgeError):
    """The benchmark data is missing or malformed."""

    code = "bench_data_error"


def synthetic_items(
    split: str = "test",
    languages: Sequence[str] = LANGUAGES,
    snr_levels: Sequence[int] = SNR_LEVELS_DB,
    *,
    limit: int | None = None,
    on_song: Callable[[SongEntry, bool], None] | None = None,
) -> list[BenchItem]:
    """Items of the synthetic suite, generating the songs that do not exist yet.

    Args:
        split: ``test``, ``dev`` or ``smoke``.
        languages: Language groups to include.
        snr_levels: Vocal-to-accompaniment ratios (dB) to include.
        limit: Use only the first ``limit`` songs of each language.
        on_song: Progress callback of the generator.
    """
    if split not in SPLITS:
        raise BenchDataError(
            f"沒有這個測資分組:{split}",
            f"Unknown split: {split}",
            hint_zh="可用:" + "、".join(SPLITS),
            hint_en="Available: " + ", ".join(SPLITS),
        )
    entries: list[SongEntry] = []
    for language in languages:
        if language not in LANGUAGES:
            raise BenchDataError(
                f"合成測資沒有這個語言:{language}",
                f"The synthetic suite has no language '{language}'.",
                hint_zh="可用:" + "、".join(LANGUAGES),
                hint_en="Available: " + ", ".join(LANGUAGES),
            )
        seeds = SPLITS[split][:limit] if limit else SPLITS[split]
        entries += [song_entry(language, seed) for seed in seeds]
    ensure_songs(entries, on_song=on_song)
    return [
        BenchItem(
            song_id=entry.song_id,
            language=entry.language,
            project_language=PROJECT_LANGUAGE[entry.language],
            audio=entry.mix(snr),
            lyrics=entry.lyrics,
            truth=entry.truth,
            snr_db=snr,
        )
        for entry in entries
        for snr in snr_levels
    ]


def real_root() -> Path:
    """Folder searched for the user's real songs (``bench/real/songs`` in a checkout)."""
    root = paths.repo_root()
    return (root / "bench" / "real" / "songs") if root else paths.home_dir() / "bench" / "real"


def _lyrics_from_project(project_file: Path, target: Path) -> tuple[str, dict[str, object]]:
    """Derive the lyrics file and the benchmark truth from a hand-corrected ``project.json``."""
    store = ProjectStore(project_file.parent)
    project = store.load()
    tags = {singer.id: singer.label for singer in project.singers}
    rows: list[str] = []
    truth_lines: list[dict[str, object]] = []
    paragraph = 0
    for line in project.lines:
        if not line.tokens:
            continue
        if not line.is_timed:
            raise BenchDataError(
                f"{project_file} 的第 {line.id} 行還有沒對齊的字,不能當作標準答案。",
                f"Line {line.id} of {project_file} has untimed tokens; it cannot serve as "
                "ground truth.",
            )
        if line.paragraph != paragraph:
            rows.append("")
            paragraph = line.paragraph
        rows.append(f"[{tags.get(line.singer, line.singer)}] {line.text}")
        truth_lines.append(
            {
                "tokens": [
                    {"text": token.text, "start_ms": token.start_ms, "end_ms": token.end_ms}
                    for token in line.tokens
                ]
            }
        )
    target.mkdir(parents=True, exist_ok=True)
    (target / "lyrics.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return project.meta.language, {"lines": truth_lines}


def real_items(root: Path | None = None, work: Path | None = None) -> list[BenchItem]:
    """Items of the real-song suite.

    Each sub-folder of ``root`` holds one song: a media file plus ``project.json``, a KaraForge
    project whose timing a person has corrected (see ``bench/real/README.md``).

    Raises:
        BenchDataError: If no usable song is found.
    """
    base = root or real_root()
    derived = work or base.parent / "_derived"
    items: list[BenchItem] = []
    if base.is_dir():
        for folder in sorted(path for path in base.iterdir() if path.is_dir()):
            project_file = folder / "project.json"
            media = next(
                (
                    path
                    for path in sorted(folder.iterdir())
                    if path.suffix.lower() in MEDIA_EXTENSIONS and path.is_file()
                ),
                None,
            )
            if media is None or not project_file.is_file():
                continue
            language, truth = _lyrics_from_project(project_file, derived / folder.name)
            truth_path = derived / folder.name / "truth.json"
            truth_path.write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
            items.append(
                BenchItem(
                    song_id=folder.name,
                    language=language.split("-")[0].lower(),
                    project_language=language,
                    audio=media,
                    lyrics=derived / folder.name / "lyrics.txt",
                    truth=truth_path,
                )
            )
    if not items:
        raise BenchDataError(
            f"在 {base} 找不到可用的真實歌曲測資。",
            f"No usable real songs found in {base}.",
            hint_zh="每首歌一個資料夾,裡面放媒體檔與人工校正過的 project.json;"
            "詳見 bench/real/README.md。",
            hint_en="Use one folder per song containing the media file and a hand-corrected "
            "project.json; see bench/real/README.md.",
        )
    return items
