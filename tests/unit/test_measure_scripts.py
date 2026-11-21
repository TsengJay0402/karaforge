"""The two measurement scripts, and the accuracy the documentation quotes for the demo."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest
import soundfile as sf


def _load(repo_root: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, repo_root / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def compare(repo_root: Path) -> ModuleType:
    return _load(repo_root, "compare_with_truth")


@pytest.fixture(scope="module")
def joiner(repo_root: Path) -> ModuleType:
    return _load(repo_root, "join_songs")


def _line(text: str, starts: list[int], length: int = 200) -> dict[str, Any]:
    return {
        "text": text,
        "tokens": [
            {"text": char, "start_ms": start, "end_ms": start + length, "confidence": 0.9}
            for char, start in zip(text, starts, strict=True)
        ],
    }


def test_identical_times_have_no_error(compare: ModuleType) -> None:
    truth = {"lines": [_line("你好嗎", [1000, 1400, 1800]), _line("再見", [5000, 5600])]}
    outcomes = compare.outcomes(truth, truth)
    assert outcomes is not None
    assert [item.start_error_ms for item in outcomes] == [0, 0, 0, 0, 0]
    assert [item.line_final for item in outcomes] == [False, False, True, False, True]
    assert compare.text_error(truth, truth) == (0, 5)


def test_errors_are_measured_per_token(compare: ModuleType) -> None:
    truth = {"lines": [_line("你好嗎", [1000, 1400, 1800]), _line("再見", [5000, 5600])]}
    project = {"lines": [_line("你好嗎", [1010, 1400, 2100]), _line("再見", [1200, 5600])]}
    outcomes = compare.outcomes(project, truth)
    assert outcomes is not None
    assert [item.start_error_ms for item in outcomes] == [10, 0, 300, 3800, 0]
    # The fourth token starts inside the first line's span: it is on the wrong line.
    assert [item.wrong_line for item in outcomes] == [False, False, False, True, False]


def test_timing_is_not_compared_when_the_lyrics_differ(compare: ModuleType) -> None:
    truth = {"lines": [_line("你好嗎", [1000, 1400, 1800])]}
    fewer_tokens = {"lines": [_line("你好", [1000, 1400])]}
    more_lines = {"lines": [_line("你好嗎", [1000, 1400, 1800]), _line("嗨", [3000])]}
    untimed = {"lines": [{"text": "你好嗎", "tokens": [{"text": char} for char in "你好嗎"]}]}
    assert compare.outcomes(fewer_tokens, truth) is None
    assert compare.outcomes(more_lines, truth) is None
    assert compare.outcomes(untimed, truth) is None


def test_text_error_ignores_spaces_punctuation_and_case(compare: ModuleType) -> None:
    truth: dict[str, Any] = {"lines": [{"text": "我們 一起唱 La La", "tokens": []}]}
    draft = {"lines": [_line("我們一起長", [0, 1, 2, 3, 4]), _line("la", [5, 6])]}
    # 「唱」 was heard as 「長」 and one "la" is missing: three characters of nine.
    assert compare.text_error(draft, truth) == (3, 9)


def test_the_demo_project_matches_the_figures_in_the_documentation(
    compare: ModuleType, repo_root: Path
) -> None:
    project = json.loads(
        (repo_root / "examples" / "demo" / "project.json").read_text(encoding="utf-8")
    )
    truth = json.loads(
        (repo_root / "tests" / "fixtures" / "songs" / "zh-2000" / "truth.json").read_text(
            encoding="utf-8"
        )
    )
    outcomes = compare.outcomes(project, truth)
    assert outcomes is not None
    errors = sorted(item.start_error_ms for item in outcomes)
    # examples/README.md: 43 tokens, median 12 ms, largest 114 ms, none above 150 ms.
    assert len(errors) == 43
    assert errors[len(errors) // 2] == 12
    assert errors[-1] == 114
    assert compare.text_error(project, truth) == (0, 43)


def test_joining_songs_shifts_the_second_song(joiner: ModuleType, tmp_path: Path) -> None:
    rate = 8000
    for name, seconds, start in (("a", 2.0, 500), ("b", 1.0, 250)):
        folder = tmp_path / name
        folder.mkdir()
        samples = np.zeros((round(seconds * rate), 1), dtype=np.float32)
        sf.write(folder / "mix.wav", samples, rate, subtype="PCM_16")
        truth = {"lines": [_line(f"歌{name}", [start, start + 300])]}
        (folder / "truth.json").write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")

    out = tmp_path / "joined"
    seconds, lines, tokens = joiner.join([tmp_path / "a", tmp_path / "b"], "mix.wav", out)

    assert (seconds, lines, tokens) == (3.0, 2, 4)
    audio, joined_rate = sf.read(out / "song.wav")
    assert joined_rate == rate and audio.shape[0] == 3 * rate
    truth = json.loads((out / "truth.json").read_text(encoding="utf-8"))
    assert [token["start_ms"] for token in truth["lines"][0]["tokens"]] == [500, 800]
    # The second song starts after the two seconds of the first.
    assert [token["start_ms"] for token in truth["lines"][1]["tokens"]] == [2250, 2550]
    lyrics = (out / "lyrics.txt").read_text(encoding="utf-8").splitlines()
    assert [line for line in lyrics if line and not line.startswith("#")] == ["歌a", "歌b"]


def test_joining_rejects_mixed_sample_rates(joiner: ModuleType, tmp_path: Path) -> None:
    for name, rate in (("a", 8000), ("b", 16000)):
        folder = tmp_path / name
        folder.mkdir()
        sf.write(folder / "mix.wav", np.zeros((rate, 1), dtype=np.float32), rate)
        (folder / "truth.json").write_text(json.dumps({"lines": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="sample rate"):
        joiner.join([tmp_path / "a", tmp_path / "b"], "mix.wav", tmp_path / "out")
