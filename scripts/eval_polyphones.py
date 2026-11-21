"""Measure the reading engine on a polyphone test set and print the result as Markdown.

Usage::

    python scripts/eval_polyphones.py [test-set.tsv] [--failures]

Without an argument the set in ``tests/fixtures/polyphones/`` is used.  The numbers in
``docs/ruby.md`` are the output of this script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "engine")]

from karaforge.text.ruby_eval import evaluate, load_cases, readers  # noqa: E402

DEFAULT_SET = REPO / "tests" / "fixtures" / "polyphones" / "zh-polyphones.tsv"


def main() -> int:
    """Print one row per reader, and optionally what each one got wrong."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("test_set", nargs="?", type=Path, default=DEFAULT_SET)
    parser.add_argument("--failures", action="store_true", help="list the misread cases")
    arguments = parser.parse_args()
    cases = load_cases(arguments.test_set)
    characters = len({case.char for case in cases})
    print(f"Test set: {arguments.test_set.name} — {len(cases)} cases, {characters} characters\n")
    print("| Reader | Correct | Accuracy |")
    print("|---|---:|---:|")
    results = {name: evaluate(cases, reader) for name, reader in readers().items()}
    for name, result in results.items():
        print(f"| {name} | {result.correct} / {result.total} | {result.accuracy:.1%} |")
    if arguments.failures:
        for name, result in results.items():
            print(f"\n### Misread by: {name}\n")
            for failure in result.failures:
                case = failure.case
                marked = (
                    f"{case.phrase[: case.index]}【{case.char}】{case.phrase[case.index + 1 :]}"
                )
                print(f"- {marked}: expected {case.expected}, got {failure.got}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
