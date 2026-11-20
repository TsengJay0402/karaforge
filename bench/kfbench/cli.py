"""Implementation of ``kf bench``."""

from __future__ import annotations

import gzip
import json
import os
import platform
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from karaforge import paths
from karaforge.device import cpu_threads, resolve_device
from karaforge.i18n import pick
from karaforge.pipeline.profiles import get_profile, parse_overrides
from kfbench.metrics import summarize
from kfbench.report import build_report
from kfbench.runner import BenchConfig, RunResult, run_matrix
from kfbench.suites import real_items, synthetic_items
from kfbench.synth.dataset import LANGUAGES, SongEntry
from kfbench.synth.song import GENERATOR_VERSION, SNR_LEVELS_DB

LONG_WINDOW_ALIGNERS = ("ctc",)
"""Aligners without a window limit, which can run the single-pass ("global") ablation."""


def source_revision() -> str:
    """Short git commit of the source checkout (``unknown`` outside a checkout)."""
    root = paths.repo_root()
    if root is None:
        return "unknown"
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "describe", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError:
        return "unknown"
    return done.stdout.strip() or "unknown"


def runs_root() -> Path:
    """Folder for working projects and reports (``bench/_runs`` in a checkout)."""
    override = os.environ.get("KARAFORGE_BENCH_RUNS")
    if override:
        return Path(override).expanduser()
    root = paths.repo_root()
    return (root / "bench" / "_runs") if root else paths.home_dir() / "bench" / "runs"


def build_configs(
    profile: str,
    aligners: list[str],
    overrides: dict[str, Any],
    *,
    ablation: bool,
    anchors: bool,
) -> tuple[list[BenchConfig], str, str | None]:
    """Expand the command-line choices into configurations.

    The **main** configuration is the profile itself (with ``overrides``), named after it;
    the specification's targets, the ablation study and the anchor experiment refer to it.
    Every entry of ``aligners`` that differs from the profile's own aligner adds a comparison
    configuration named ``<profile>+<aligner>``.

    Returns:
        The configurations, the name of the main one and the name of the random-anchor
        configuration, if any.
    """
    main_aligner = get_profile(profile).with_overrides(overrides).align.aligner
    configs: list[BenchConfig] = [BenchConfig(name=profile, profile=profile, overrides=overrides)]
    if ablation:
        variants: list[tuple[str, dict[str, Any]]] = [
            ("no-coarse(regions)", {"align.coarse": "regions"}),
            ("no-onset-snap", {"align.onset_snap": False}),
            ("no-weak-rescue", {"align.weak_score": 0}),
            ("no-long-note", {"align.long_note": False}),
        ]
        if main_aligner in LONG_WINDOW_ALIGNERS:
            variants.insert(1, ("no-coarse(global)", {"align.coarse": "global"}))
        configs += [
            BenchConfig(
                name=f"{profile} / {label}", profile=profile, overrides={**overrides, **change}
            )
            for label, change in variants
        ]
    if anchors:
        configs += [
            BenchConfig(
                name=f"{profile} / anchors-random-5%",
                profile=profile,
                overrides=overrides,
                anchors="random",
            ),
            BenchConfig(
                name=f"{profile} / anchors-lowconf-5%",
                profile=profile,
                overrides=overrides,
                anchors="low-confidence",
            ),
        ]
    for aligner in dict.fromkeys(aligners):
        if aligner == main_aligner:
            continue
        configs.append(
            BenchConfig(
                name=f"{profile}+{aligner}",
                profile=profile,
                overrides={**overrides, "align.aligner": aligner, "align.model": "default"},
            )
        )
    anchor_name = f"{profile} / anchors-random-5%" if anchors else None
    return configs, profile, anchor_name


def run_bench(
    *,
    suite: str = "synthetic",
    split: str = "test",
    profile: str = "balanced",
    aligners: list[str] | None = None,
    settings: list[str] | None = None,
    languages: list[str] | None = None,
    snr_levels: list[int] | None = None,
    limit: int | None = None,
    ablation: bool = False,
    anchors: bool = True,
    output: Path | None = None,
    console: Console | None = None,
) -> Path:
    """Run a benchmark and write ``report.md`` / ``results.json`` / ``tokens.json.gz``.

    Returns:
        The output folder.
    """
    log = console or Console()
    # Read before any work: a run takes hours, and the checkout may move on meanwhile while
    # this process keeps running the code it loaded at the start.
    commit = source_revision()
    started = datetime.now().astimezone()
    overrides = parse_overrides(settings or [])
    configs, main_name, anchor_name = build_configs(
        profile, aligners or [], overrides, ablation=ablation, anchors=anchors
    )
    work = (
        runs_root()
        / "work"
        / (f"synthetic-v{GENERATOR_VERSION}" if suite == "synthetic" else "real")
    )

    if suite == "synthetic":

        def on_song(entry: SongEntry, made: bool) -> None:
            if made:
                log.print(pick(f"  已產生測資 {entry.song_id}", f"  generated {entry.song_id}"))

        items = synthetic_items(
            split,
            languages or list(LANGUAGES),
            snr_levels or list(SNR_LEVELS_DB),
            limit=limit,
            on_song=on_song,
        )
        title = f"KaraForge 合成測資評測({split},產生器 v{GENERATOR_VERSION})"
    else:
        items = real_items()
        title = "KaraForge 真實歌曲評測"

    log.print(
        pick(
            f"評測:{len(items)} 個音檔 × {len(configs)} 種設定",
            f"Benchmark: {len(items)} audio files × {len(configs)} configurations",
        )
    )

    def on_result(result: RunResult) -> None:
        summary = summarize(result.outcomes)
        if summary is None:
            return
        log.print(
            f"  {result.item:16s} {result.config:44s} median {summary.median_ms:5.0f} ms  "
            f"P95 {summary.p95_ms:5.0f}  >150ms {summary.needs_fix_pct:5.1f}%",
            highlight=False,
        )

    results = run_matrix(items, configs, work, on_result=on_result)
    device = resolve_device(get_profile(profile).device)
    markdown, document = build_report(
        results,
        title=title,
        main_config=main_name,
        anchor_config=anchor_name,
        notes=[
            f"分組 `{split}`;設定檔 `{profile}`;音檔 {len(items)} 個。"
            if suite == "synthetic"
            else f"真實歌曲 {len(items)} 首。",
        ],
        environment={
            "cpu": platform.processor() or platform.machine(),
            "threads": str(cpu_threads()),
            "device": device.kind,
            "commit": commit,
            "started": started.isoformat(timespec="seconds"),
            "finished": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )
    target = output or runs_root() / "reports" / f"{suite}-{split}-{profile}"
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.md").write_text(markdown, encoding="utf-8")
    (target / "results.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    with gzip.open(target / "tokens.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(
            [
                {
                    "item": result.item,
                    "config": result.config,
                    "tokens": [asdict(outcome) for outcome in result.outcomes],
                }
                for result in results
            ],
            handle,
            ensure_ascii=False,
        )
    log.print(pick(f"報告:{target / 'report.md'}", f"Report: {target / 'report.md'}"))
    return target
