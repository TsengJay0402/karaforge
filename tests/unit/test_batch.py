from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

from karaforge.batch import BatchItem, plan_batch, project_dir_for
from karaforge.errors import MediaError


def make(folder: Path, *names: str) -> None:
    """Create empty files in ``folder`` — :func:`plan_batch` only looks at names."""
    for name in names:
        (folder / name).write_bytes(b"")


def names(plan_items: tuple[BatchItem, ...]) -> list[str]:
    return [item.name for item in plan_items]


def test_pairs_media_with_lyrics_sorted_by_name(tmp_path: Path) -> None:
    make(tmp_path, "夜空.mp3", "b.flac", "夜空.txt", "b.lrc")
    plan = plan_batch(tmp_path)
    assert names(plan.items) == ["b", "夜空"]
    first, second = plan.items
    assert first.media == tmp_path / "b.flac"
    assert first.lyrics == tmp_path / "b.lrc"
    assert second.media == tmp_path / "夜空.mp3"
    assert second.lyrics == tmp_path / "夜空.txt"


def test_media_without_lyrics_has_lyrics_none(tmp_path: Path) -> None:
    make(tmp_path, "song.mp3")
    plan = plan_batch(tmp_path)
    assert len(plan.items) == 1
    assert plan.items[0].media == tmp_path / "song.mp3"
    assert plan.items[0].lyrics is None


def test_lyrics_without_media_are_unmatched(tmp_path: Path) -> None:
    make(tmp_path, "song.mp3", "orphan.txt", "another.lrc")
    plan = plan_batch(tmp_path)
    assert names(plan.items) == ["song"]
    assert list(plan.unmatched_lyrics) == [tmp_path / "another.lrc", tmp_path / "orphan.txt"]


def test_duplicate_media_prefers_first_extension_in_media_order(tmp_path: Path) -> None:
    make(tmp_path, "song.mp4", "song.mp3")
    plan = plan_batch(tmp_path)
    assert len(plan.items) == 1
    assert plan.items[0].media == tmp_path / "song.mp4"  # .mp4 comes before .mp3
    assert list(plan.duplicates) == [tmp_path / "song.mp3"]


def test_duplicate_lyrics_prefers_first_extension_in_lyrics_order(tmp_path: Path) -> None:
    make(tmp_path, "song.mp3", "song.lrc", "song.txt")
    plan = plan_batch(tmp_path)
    assert len(plan.items) == 1
    assert plan.items[0].lyrics == tmp_path / "song.txt"  # .txt comes before .lrc
    assert plan.duplicates == ()


def test_extension_case_is_ignored_when_pairing(tmp_path: Path) -> None:
    make(tmp_path, "Song.MP3", "song.txt")
    plan = plan_batch(tmp_path)
    assert len(plan.items) == 1
    assert plan.items[0].media == tmp_path / "Song.MP3"
    assert plan.items[0].lyrics == tmp_path / "song.txt"


def test_ignores_dotfiles_subfolders_and_other_extensions(tmp_path: Path) -> None:
    make(tmp_path, ".hidden.mp3", ".hidden.txt", "cover.jpg", "notes.md")
    (tmp_path / "sub").mkdir()
    make(tmp_path / "sub", "nested.mp3", "nested.txt")
    plan = plan_batch(tmp_path)
    assert plan.items == ()
    assert plan.unmatched_lyrics == ()
    assert plan.duplicates == ()


def test_pairs_nfc_and_nfd_spellings_of_the_same_name(tmp_path: Path) -> None:
    nfd_name = unicodedata.normalize("NFD", "café")
    nfc_name = unicodedata.normalize("NFC", "café")
    assert nfd_name != nfc_name
    make(tmp_path, f"{nfd_name}.mp3", f"{nfc_name}.txt")
    plan = plan_batch(tmp_path)
    assert len(plan.items) == 1
    # Some file systems normalise names themselves, so compare the normalised spellings.
    lyrics = plan.items[0].lyrics
    assert lyrics is not None
    assert unicodedata.normalize("NFC", plan.items[0].media.name) == "café.mp3"
    assert unicodedata.normalize("NFC", lyrics.name) == "café.txt"
    assert plan.unmatched_lyrics == ()


def test_missing_folder_raises_media_error(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(MediaError, match=re.escape(str(missing))):
        plan_batch(missing)


def test_project_dir_for_appends_project_suffix(tmp_path: Path) -> None:
    item = BatchItem(tmp_path / "café.mp3", None)
    out = tmp_path / "export"
    assert project_dir_for(item, out) == out / "café.kfproj"
    assert project_dir_for(item, out).parent == out
