"""Compare alignment settings on the development split.

Separation, analysis and speech recognition are taken from the working projects' caches (and
computed first if missing); only the alignment itself is repeated for every variant, in one
process, so that a grid of settings costs seconds per song instead of minutes.

This tool exists to keep tuning honest: it refuses to run on the ``test`` split.  The values
chosen with it are recorded in ``docs/adr/0006-aligner-choice.md``.

Usage::

    python -m kfbench.tune --aligner ctc --aligner whisper-attn \
        --grid align.onset_snap_ms=40,60,80 --snr 10
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from rich.console import Console

from karaforge.adapters.base import AsrWord
from karaforge.adapters.registry import create_aligner
from karaforge.align.coarse import LyricLine
from karaforge.align.engine import AlignmentOutput, lyric_lines, run_alignment
from karaforge.align.features import VocalFeatures
from karaforge.audio.io import FloatArray, read_mono
from karaforge.device import resolve_device
from karaforge.pipeline.profiles import Profile, get_profile, parse_overrides
from karaforge.project.create import create_or_update_project
from karaforge.stages.analyze import FEATURES_FILE, load_features
from karaforge.stages.asr import TRANSCRIPT_FILE, load_transcript
from karaforge.stages.standard import run_pipeline
from kfbench.cli import runs_root
from kfbench.metrics import TokenOutcome, summarize, wrong_line
from kfbench.runner import BenchItem, load_truth, reset_lyrics
from kfbench.suites import synthetic_items
from kfbench.synth.dataset import LANGUAGES
from kfbench.synth.song import GENERATOR_VERSION, SNR_LEVELS_DB

TUNING_SPLITS = ("dev", "smoke")


@dataclass
class Prepared:
    """Everything the alignment needs for one item, loaded once."""

    item: BenchItem
    lines: list[LyricLine]
    audio: FloatArray
    features: VocalFeatures
    words: list[AsrWord]
    language: str
    truth: list[list[dict[str, Any]]]


def prepare_item(item: BenchItem, work_root: Path, profile: Profile) -> Prepared:
    """Bring an item's project up to the alignment stage and load its inputs."""
    store, _created = create_or_update_project(
        item.audio,
        work_root / f"{item.key}.kfproj",
        lyrics=item.lyrics,
        language=item.project_language,
    )
    project = reset_lyrics(store, item.lyrics)
    report = run_pipeline(store, profile=profile, targets=("analyze", "asr"))
    cache = store.paths.cache
    features = load_features(cache / "analyze" / str(report["analyze"].key) / FEATURES_FILE)
    transcript = load_transcript(cache / "asr" / str(report["asr"].key) / TRANSCRIPT_FILE)
    return Prepared(
        item=item,
        lines=lyric_lines(project),
        audio=read_mono(store.paths.media / "vocals.wav"),
        features=features,
        words=transcript.words,
        language=project.meta.language,
        truth=load_truth(item.truth),
    )


def outcomes_of(prepared: Prepared, output: AlignmentOutput) -> list[TokenOutcome]:
    """Pair the alignment's tokens with the ground truth."""
    truth = prepared.truth
    if len(output.tokens) != len(truth):
        raise ValueError(f"{prepared.item.key}: line count differs from the truth")
    spans = [(int(tokens[0]["start_ms"]), int(tokens[-1]["end_ms"])) for tokens in truth]
    result: list[TokenOutcome] = []
    for line_index, (tokens, expected, confidences) in enumerate(
        zip(output.tokens, truth, output.confidences, strict=True)
    ):
        for index, (token, reference, confidence) in enumerate(
            zip(tokens, expected, confidences, strict=True)
        ):
            start = round(token.start_s * 1000)
            result.append(
                TokenOutcome(
                    song=prepared.item.song_id,
                    line=line_index,
                    index=index,
                    text=str(reference["text"]),
                    true_start_ms=int(reference["start_ms"]),
                    true_end_ms=int(reference["end_ms"]),
                    pred_start_ms=start,
                    pred_end_ms=round(token.end_s * 1000),
                    confidence=confidence,
                    locked=token.locked,
                    line_final=index == len(tokens) - 1,
                    wrong_line=wrong_line(start, line_index, spans),
                )
            )
    return result


def align_variant(prepared: Prepared, profile: Profile) -> tuple[list[TokenOutcome], list[float]]:
    """Run the alignment of one variant on one item.

    Returns:
        The token outcomes and, in the same order, the aligner's own score of each token.
    """
    aligner = create_aligner(profile.align, profile.asr, resolve_device(profile.device))
    output = run_alignment(
        prepared.lines,
        audio=prepared.audio,
        features=prepared.features,
        words=prepared.words,
        aligner=aligner,
        settings=profile.align,
        language=prepared.language,
        max_window_s=getattr(aligner, "max_window_s", None),
    )
    scores = [round(token.score, 4) for line in output.tokens for token in line]
    return outcomes_of(prepared, output), scores


def expand_grid(aligners: Sequence[str], grid: Sequence[str]) -> list[dict[str, Any]]:
    """All combinations of the aligners and the ``key=v1,v2`` grid entries.

    Raises:
        ValueError: If a grid key is not an ``align.*`` setting (anything else would change
            stages whose results are reused across variants).
    """
    axes: list[list[tuple[str, Any]]] = []
    if aligners:
        axes.append([("align.aligner", name) for name in aligners])
    for entry in grid:
        key, separator, values = entry.partition("=")
        if not separator or not key.startswith("align."):
            raise ValueError(f"grid entries look like align.name=v1,v2 (got {entry!r})")
        parsed = [parse_overrides([f"{key}={value}"])[key] for value in values.split(",")]
        axes.append([(key, value) for value in parsed])
    return [dict(combination) for combination in itertools.product(*axes)] or [{}]


def label_of(variant: dict[str, Any]) -> str:
    """Short name of a variant for the result table."""
    if not variant:
        return "(profile defaults)"
    return " ".join(f"{key.removeprefix('align.')}={value}" for key, value in variant.items())


def format_table(rows: dict[str, dict[str, list[TokenOutcome]]], groups: Sequence[str]) -> str:
    """A Markdown table: one row per variant and group."""
    lines = [
        "| variant | group | tokens | median | P90 | P95 | >150 ms | wrong line | bias |"
        " end median | AUROC |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, by_group in rows.items():
        for group in groups:
            summary = summarize(by_group.get(group, []))
            if summary is None:
                continue
            auroc = "–" if summary.confidence_auroc is None else f"{summary.confidence_auroc:.2f}"
            lines.append(
                f"| `{label}` | {group} | {summary.tokens} | {summary.median_ms:.0f} | "
                f"{summary.p90_ms:.0f} | {summary.p95_ms:.0f} | {summary.needs_fix_pct:.1f}% | "
                f"{summary.line_mismatch_pct:.1f}% | {summary.bias_ms:+.0f} | "
                f"{summary.line_end_median_ms:.0f} | {auroc} |"
            )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--split", default="dev", choices=TUNING_SPLITS)
    parser.add_argument("--profile", default="balanced")
    parser.add_argument("--aligner", action="append", default=[])
    parser.add_argument("--grid", action="append", default=[], metavar="align.KEY=V1,V2")
    parser.add_argument("--set", action="append", default=[], dest="settings", metavar="KEY=VALUE")
    parser.add_argument("--language", action="append", default=[], choices=LANGUAGES)
    parser.add_argument("--snr", action="append", type=int, default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dump", type=Path, default=None, help="write per-token results (JSON)")
    arguments = parser.parse_args(argv)
    log = Console()

    base = get_profile(arguments.profile).with_overrides(parse_overrides(arguments.settings))
    variants = expand_grid(arguments.aligner, arguments.grid)
    languages = arguments.language or list(LANGUAGES)
    items = synthetic_items(
        arguments.split, languages, arguments.snr or list(SNR_LEVELS_DB), limit=arguments.limit
    )
    work_root = runs_root() / "work" / f"synthetic-v{GENERATOR_VERSION}"
    log.print(f"{len(items)} items x {len(variants)} variants", highlight=False)

    rows: dict[str, dict[str, list[TokenOutcome]]] = {label_of(v): {} for v in variants}
    dump: list[dict[str, Any]] = []
    for position, item in enumerate(items, start=1):
        prepared = prepare_item(item, work_root, base)
        for variant in variants:
            outcomes, scores = align_variant(prepared, base.with_overrides(variant))
            label = label_of(variant)
            for group in ("all", item.language, f"{item.language}@{item.snr_db}dB"):
                rows[label].setdefault(group, []).extend(outcomes)
            if arguments.dump is not None:
                dump.append(
                    {
                        "item": item.key,
                        "variant": label,
                        "tokens": [
                            {
                                "line": o.line,
                                "index": o.index,
                                "text": o.text,
                                "true": o.true_start_ms,
                                "pred": o.pred_start_ms,
                                "confidence": o.confidence,
                                "score": score,
                            }
                            for o, score in zip(outcomes, scores, strict=True)
                        ],
                    }
                )
        errors = np.array([o.start_error_ms for o in rows[label_of(variants[0])]["all"]])
        log.print(
            f"  [{position}/{len(items)}] {item.key}  running median of first variant: "
            f"{np.median(errors):.0f} ms",
            highlight=False,
        )

    groups = ["all", *languages]
    groups += [
        f"{language}@{snr}dB" for language in languages for snr in sorted(set(arguments.snr))
    ]
    log.print()
    log.print(format_table(rows, groups), markup=False, highlight=False, soft_wrap=True)
    if arguments.dump is not None:
        arguments.dump.parent.mkdir(parents=True, exist_ok=True)
        arguments.dump.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
