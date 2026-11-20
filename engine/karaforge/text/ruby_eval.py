"""Measuring how often the reading engine picks the right reading of a polyphonic character.

A test set is a text file with one case per line: a phrase in which the character between
``【`` and ``】`` is the one being tested, a tab, and the expected reading as Pinyin with a
tone digit (``5`` for the neutral tone).  Lines starting with ``#`` are comments.  The set
that ships with the source tree is ``tests/fixtures/polyphones/zh-polyphones.tsv``; the same
format works for a list of your own (``python scripts/eval_polyphones.py my-list.tsv``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pypinyin import Style, pinyin

from karaforge.errors import LyricsFormatError
from karaforge.text.ruby import _simplify, han_readings  # pyright: ignore[reportPrivateUsage]
from karaforge.text.tokenize import is_han

Reader = Callable[[str], Sequence[str | None]]
"""Maps a phrase to one reading per character."""


@dataclass(frozen=True)
class PolyphoneCase:
    """One test case."""

    phrase: str
    """The phrase without the markers."""
    index: int
    """Position of the tested character in ``phrase``."""
    expected: str

    @property
    def char(self) -> str:
        """The tested character."""
        return self.phrase[self.index]


@dataclass(frozen=True)
class Failure:
    """A case that was read differently from what the test set expects."""

    case: PolyphoneCase
    got: str | None


@dataclass(frozen=True)
class Evaluation:
    """Outcome of one reader on a test set."""

    total: int
    failures: tuple[Failure, ...]

    @property
    def correct(self) -> int:
        """Number of cases read as expected."""
        return self.total - len(self.failures)

    @property
    def accuracy(self) -> float:
        """Share of cases read as expected (0 for an empty set)."""
        return self.correct / self.total if self.total else 0.0


def load_cases(path: Path) -> list[PolyphoneCase]:
    """Read a test set.

    Raises:
        LyricsFormatError: If a line is not ``phrase with 【字】<TAB>reading``.
    """
    cases: list[PolyphoneCase] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        marked, separator, expected = line.partition("\t")
        opening = marked.find("【")
        valid = (
            separator
            and expected.strip()
            and marked.count("【") == 1
            and marked.count("】") == 1
            and marked.find("】") == opening + 2
        )
        if not valid:
            raise LyricsFormatError(
                f"{path.name} 第 {number} 行的格式不對。",
                f"Line {number} of {path.name} is malformed.",
                hint_zh="格式:含有一個【字】的句子、Tab、預期讀音(如 hang2)。",
                hint_en="Expected: a phrase with one 【char】, a tab, the reading (e.g. hang2).",
                detail=raw,
            )
        phrase = marked.replace("【", "").replace("】", "")
        cases.append(PolyphoneCase(phrase, opening, expected.strip()))
    return cases


def evaluate(cases: Sequence[PolyphoneCase], reader: Reader) -> Evaluation:
    """Run ``reader`` on every case and compare the tested character's reading."""
    failures: list[Failure] = []
    for case in cases:
        readings = reader(case.phrase)
        got = readings[case.index] if case.index < len(readings) else None
        if got != case.expected:
            failures.append(Failure(case, got))
    return Evaluation(len(cases), tuple(failures))


def plain_pypinyin(text: str, *, simplify: bool) -> list[str | None]:
    """Readings straight from pypinyin, without any of KaraForge's rules.

    The baseline the engine is compared with.  With ``simplify`` the text is first converted
    to Simplified, which is what pypinyin's word list is written in.
    """
    source = _simplify(text) if simplify else text
    result: list[str | None] = []
    position = 0
    for chunk in pinyin(source, style=Style.TONE3, neutral_tone_with_five=True):
        value = chunk[0] if chunk else ""
        if position < len(source) and is_han(source[position]):
            result.append(value if value and value[-1].isdigit() else None)
            position += 1
        else:
            # pypinyin returns a run of other characters as one item.
            width = len(value) or 1
            result.extend([None] * width)
            position += width
    return (result + [None] * len(text))[: len(text)]


def readers() -> dict[str, Reader]:
    """The engine and its baselines, by display name."""
    return {
        "pypinyin on the text as written": lambda text: plain_pypinyin(text, simplify=False),
        "pypinyin on Simplified text": lambda text: plain_pypinyin(text, simplify=True),
        "KaraForge (Taiwan readings)": lambda text: han_readings(text, taiwan=True),
        "KaraForge (Mainland readings)": lambda text: han_readings(text, taiwan=False),
    }
