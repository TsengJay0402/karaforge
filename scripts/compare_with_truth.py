"""Compare a processed project with the known answer of a synthetic song.

The synthetic songs (``tests/fixtures/songs`` and the benchmark data) come with a
``truth.json`` that holds the true time of every token.  ``kf bench`` uses it for whole test
sets; this script does the same for one project, with the same definitions::

    kf auto song.mp3 lyrics.txt -o song-ktv.mp4
    python scripts/compare_with_truth.py song-ktv.kfproj truth.json

Timing is compared when the project has the lyrics of the truth file, token for token.  The
lyrics themselves are compared too (character error rate), which is what matters for a
project whose lyrics were drafted by speech recognition::

    kf auto song.mp3 -o draft-ktv.mp4
    python scripts/compare_with_truth.py draft-ktv.kfproj truth.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median
from typing import Any

from rapidfuzz.distance import Levenshtein

from karaforge.text.tokenize import is_han
from kfbench.metrics import FIX_THRESHOLD_MS, TokenOutcome, summarize, wrong_line


def _load(path: Path) -> dict[str, Any]:
    if path.is_dir():
        path = path / "project.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _comparable(text: str) -> str:
    """The characters that count for the error rate: Han characters, letters and digits."""
    return "".join(char.lower() for char in text if is_han(char) or char.isalnum())


def text_error(project: dict[str, Any], truth: dict[str, Any]) -> tuple[int, int]:
    """Edit distance between the project's lyrics and the true ones, and the true length."""
    reference = _comparable("".join(line["text"] for line in truth["lines"]))
    written = _comparable(
        "".join(token["text"] for line in project["lines"] for token in line["tokens"])
    )
    return Levenshtein.distance(reference, written), len(reference)


def outcomes(project: dict[str, Any], truth: dict[str, Any]) -> list[TokenOutcome] | None:
    """One outcome per token, or ``None`` when the project's lyrics differ from the truth."""
    predicted: list[dict[str, Any]] = project["lines"]
    expected: list[dict[str, Any]] = truth["lines"]
    if len(predicted) != len(expected) or any(
        len(line["tokens"]) != len(answer["tokens"])
        for line, answer in zip(predicted, expected, strict=True)
    ):
        return None
    spans = [
        (int(answer["tokens"][0]["start_ms"]), int(answer["tokens"][-1]["end_ms"]))
        for answer in expected
    ]
    found: list[TokenOutcome] = []
    for number, (line, answer) in enumerate(zip(predicted, expected, strict=True)):
        last = len(line["tokens"]) - 1
        for index, (token, true) in enumerate(zip(line["tokens"], answer["tokens"], strict=True)):
            if token.get("start_ms") is None or token.get("end_ms") is None:
                return None
            found.append(
                TokenOutcome(
                    song=str(truth.get("song_id", "")),
                    line=number,
                    index=index,
                    text=str(token["text"]),
                    true_start_ms=int(true["start_ms"]),
                    true_end_ms=int(true["end_ms"]),
                    pred_start_ms=int(token["start_ms"]),
                    pred_end_ms=int(token["end_ms"]),
                    confidence=float(token.get("confidence") or 0.0),
                    locked=False,
                    line_final=index == last,
                    wrong_line=wrong_line(int(token["start_ms"]), number, spans),
                )
            )
    return found


def main() -> int:
    """Print the comparison."""
    parser = argparse.ArgumentParser(
        description="Compare a processed project with the known answer of a synthetic song."
    )
    parser.add_argument("project", type=Path, help="a .kfproj folder or a project.json")
    parser.add_argument("truth", type=Path, help="the truth.json of the same song")
    arguments = parser.parse_args()
    project = _load(arguments.project)
    truth = _load(arguments.truth)

    errors, length = text_error(project, truth)
    source = project.get("meta", {}).get("lyrics_source", "user")
    print(f"lyrics ({source}): {errors} of {length} characters differ = {errors / length:.1%}")

    tokens = outcomes(project, truth)
    if tokens is None:
        print("timing: not compared — the project's lines or tokens differ from the truth file")
        return 0
    summary = summarize(tokens)
    if summary is None:
        print("timing: no tokens")
        return 0
    worst = max(token.start_error_ms for token in tokens)
    lines = sorted({token.line for token in tokens})
    displaced = [
        number
        for number in lines
        if median(t.start_error_ms for t in tokens if t.line == number) > FIX_THRESHOLD_MS
    ]
    print(
        f"timing: {summary.tokens} tokens in {len(lines)} lines — start error median "
        f"{summary.median_ms:.0f} ms, P95 {summary.p95_ms:.0f} ms, max {worst} ms; "
        f"{summary.needs_fix_pct:.1f}% over {FIX_THRESHOLD_MS} ms; "
        f"{len(displaced)} lines mostly off (line median over {FIX_THRESHOLD_MS} ms)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
