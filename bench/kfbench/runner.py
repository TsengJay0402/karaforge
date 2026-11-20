"""Runs benchmark configurations on songs and collects per-token outcomes.

One working project is kept per ``(song, SNR)`` and shared by all configurations, so the
expensive stages (separation, analysis, speech recognition) run once and every further
configuration — another aligner, an ablation, the anchor experiment — only repeats the
alignment itself.  That reuse is the pipeline's content-hash cache at work, not a shortcut:
each configuration still goes through ``run_pipeline`` exactly as ``kf run`` would.
"""

from __future__ import annotations

import json
import math
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from karaforge.io.importers.lyrics_txt import parse_lyrics_file
from karaforge.pipeline.profiles import get_profile
from karaforge.pipeline.runner import ELAPSED_KEY
from karaforge.project import Project, ProjectStore
from karaforge.project.create import create_or_update_project
from karaforge.runtime import CancelToken
from karaforge.stages.standard import run_pipeline
from kfbench.metrics import TokenOutcome, wrong_line

AnchorMode = Literal["none", "random", "low-confidence"]
PROCESS_STAGES = ("ingest", "separate", "analyze", "asr", "align")


@dataclass(frozen=True)
class BenchConfig:
    """One system configuration to evaluate."""

    name: str
    profile: str = "balanced"
    overrides: dict[str, Any] = field(default_factory=dict[str, Any])
    anchors: AnchorMode = "none"
    anchor_share: float = 0.05
    """Share of tokens set to the truth and locked, for the anchor experiment."""
    anchor_seed: str | None = None
    """Name that seeds the random choice of anchors (default: the configuration's own name).
    Two configurations with the same seed name lock exactly the same tokens."""


@dataclass(frozen=True)
class BenchItem:
    """One piece of audio with ground truth."""

    song_id: str
    language: str
    """Benchmark language group (``zh``, ``en``, ``mixed`` or whatever the suite uses)."""
    project_language: str
    audio: Path
    lyrics: Path
    truth: Path
    snr_db: int | None = None

    @property
    def key(self) -> str:
        """Unique name of the item (also the working project's folder name)."""
        return self.song_id if self.snr_db is None else f"{self.song_id}-snr{self.snr_db:02d}"


@dataclass
class RunResult:
    """Outcome of one configuration on one item."""

    item: str
    song: str
    language: str
    snr_db: int | None
    config: str
    outcomes: list[TokenOutcome]
    stage_seconds: dict[str, float]
    audio_seconds: float
    windows_from: dict[str, int]
    anchors: int = 0

    @property
    def processing_seconds(self) -> float:
        """Total compute time of the processing stages."""
        return sum(self.stage_seconds.values())

    @property
    def realtime_factor(self) -> float:
        """Seconds of audio processed per second of computing."""
        total = self.processing_seconds
        return self.audio_seconds / total if total > 0 else math.inf


def load_truth(path: Path) -> list[list[dict[str, Any]]]:
    """Ground-truth tokens per line: dictionaries with ``text``, ``start_ms`` and ``end_ms``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [list(line["tokens"]) for line in data["lines"]]


def reset_lyrics(store: ProjectStore, lyrics: Path) -> Project:
    """Put the project's lines back to the untimed, unlocked state of the lyrics file."""
    project = store.load()
    parsed = parse_lyrics_file(lyrics)
    project.singers = parsed.singers
    project.lines = parsed.lines
    store.save(project)
    return project


def collect_outcomes(
    project: Project, truth: list[list[dict[str, Any]]], song: str
) -> list[TokenOutcome]:
    """Pair every predicted token with its ground truth.

    Raises:
        ValueError: If the project's lines do not correspond to the truth.
    """
    lines = [line for line in project.lines if line.tokens]
    if len(lines) != len(truth):
        raise ValueError(f"{song}: {len(lines)} lines aligned but the truth has {len(truth)}")
    spans = [(int(tokens[0]["start_ms"]), int(tokens[-1]["end_ms"])) for tokens in truth]
    outcomes: list[TokenOutcome] = []
    for line_index, (line, expected) in enumerate(zip(lines, truth, strict=True)):
        if len(line.tokens) != len(expected):
            raise ValueError(f"{song} line {line_index}: token count differs from the truth")
        for index, (token, reference) in enumerate(zip(line.tokens, expected, strict=True)):
            if token.start_ms is None or token.end_ms is None:
                raise ValueError(f"{song} line {line_index} token {index} was not aligned")
            outcomes.append(
                TokenOutcome(
                    song=song,
                    line=line_index,
                    index=index,
                    text=token.text,
                    true_start_ms=int(reference["start_ms"]),
                    true_end_ms=int(reference["end_ms"]),
                    pred_start_ms=token.start_ms,
                    pred_end_ms=token.end_ms,
                    confidence=token.confidence if token.confidence is not None else 0.0,
                    locked=token.locked,
                    line_final=index == len(line.tokens) - 1,
                    wrong_line=wrong_line(token.start_ms, line_index, spans),
                )
            )
    return outcomes


def choose_anchors(
    outcomes: Sequence[TokenOutcome], mode: AnchorMode, share: float, seed_text: str
) -> list[tuple[int, int]]:
    """Pick the ``(line, index)`` of the tokens to lock for the anchor experiment.

    ``random`` draws uniformly (reproducibly, seeded by ``seed_text``); ``low-confidence``
    takes the tokens the system itself is least sure about — what the editor highlights.
    """
    count = max(1, round(len(outcomes) * share))
    if mode == "random":
        rng = np.random.default_rng(zlib.crc32(seed_text.encode("utf-8")))
        picked = rng.choice(len(outcomes), size=min(count, len(outcomes)), replace=False)
        chosen = [outcomes[int(position)] for position in sorted(int(p) for p in picked)]
    else:
        chosen = sorted(outcomes, key=lambda outcome: outcome.confidence)[:count]
    return [(outcome.line, outcome.index) for outcome in chosen]


def lock_to_truth(
    store: ProjectStore, truth: list[list[dict[str, Any]]], anchors: Sequence[tuple[int, int]]
) -> None:
    """Set the chosen tokens to their true times and lock them, as a user's correction would."""
    project = store.load()
    lines = [line for line in project.lines if line.tokens]
    for line_index, index in anchors:
        reference = truth[line_index][index]
        token = lines[line_index].tokens[index]
        lines[line_index].tokens[index] = token.retimed(
            int(reference["start_ms"]),
            int(reference["end_ms"]),
            confidence=1.0,
            source="manual",
            locked=True,
        )
    store.save(project)


def run_config(
    item: BenchItem,
    config: BenchConfig,
    work_root: Path,
    *,
    cancel: CancelToken | None = None,
) -> RunResult:
    """Evaluate one configuration on one item.

    Args:
        item: Audio, lyrics and ground truth.
        config: Profile, overrides and anchor mode.
        work_root: Folder for the working projects (one per item, reused across configs).
        cancel: Cancellation token.
    """
    store, _created = create_or_update_project(
        item.audio,
        work_root / f"{item.key}.kfproj",
        lyrics=item.lyrics,
        language=item.project_language,
    )
    truth = load_truth(item.truth)
    profile = get_profile(config.profile).with_overrides(config.overrides)

    reset_lyrics(store, item.lyrics)
    report = run_pipeline(store, profile=profile, cancel=cancel)
    anchors: list[tuple[int, int]] = []
    if config.anchors != "none":
        baseline = collect_outcomes(store.load(), truth, item.song_id)
        anchors = choose_anchors(
            baseline,
            config.anchors,
            config.anchor_share,
            f"{item.key}/{config.anchor_seed or config.name}",
        )
        lock_to_truth(store, truth, anchors)
        report = run_pipeline(store, profile=profile, cancel=cancel)

    project = store.load()
    stage_seconds = {
        stage: float(report[stage].result.get(ELAPSED_KEY, 0.0))
        for stage in PROCESS_STAGES
        if stage in report
    }
    windows: dict[str, int] = dict(report["align"].result.get("windows_from", {}))
    return RunResult(
        item=item.key,
        song=item.song_id,
        language=item.language,
        snr_db=item.snr_db,
        config=config.name,
        outcomes=collect_outcomes(project, truth, item.song_id),
        stage_seconds=stage_seconds,
        audio_seconds=project.meta.duration_ms / 1000.0,
        windows_from=windows,
        anchors=len(anchors),
    )


def run_matrix(
    items: Sequence[BenchItem],
    configs: Sequence[BenchConfig],
    work_root: Path,
    *,
    on_result: Callable[[RunResult], None] | None = None,
    cancel: CancelToken | None = None,
) -> list[RunResult]:
    """Evaluate every configuration on every item (items outermost, to keep caches warm)."""
    results: list[RunResult] = []
    for item in items:
        for config in configs:
            result = run_config(item, config, work_root, cancel=cancel)
            results.append(result)
            if on_result is not None:
                on_result(result)
    return results
