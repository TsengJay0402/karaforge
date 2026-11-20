"""Turns benchmark results into a Markdown report and a JSON document."""

from __future__ import annotations

import datetime
import platform
from collections.abc import Sequence
from typing import Any

import numpy as np

from karaforge import __version__
from kfbench.metrics import FIX_THRESHOLD_MS, Summary, TokenOutcome, summarize
from kfbench.runner import PROCESS_STAGES, RunResult

TARGETS = {
    "median_ms": 60.0,
    "p95_ms": 250.0,
    "needs_fix_pct": 10.0,
    "needs_fix_after_anchors_pct": 5.0,
}
"""Targets of SPEC §10.4 (``balanced`` profile, Chinese, 10 dB)."""


def _fmt(value: float | None, digits: int = 0) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _snr(value: int | None) -> str:
    return "–" if value is None else f"{value} dB"


def group(results: Sequence[RunResult]) -> dict[tuple[str, str, int | None], list[TokenOutcome]]:
    """Pool token outcomes by ``(config, language, snr)``."""
    pooled: dict[tuple[str, str, int | None], list[TokenOutcome]] = {}
    for result in results:
        pooled.setdefault((result.config, result.language, result.snr_db), []).extend(
            result.outcomes
        )
    return pooled


def summaries(results: Sequence[RunResult]) -> list[dict[str, Any]]:
    """One summary row per ``(config, language, snr)``, in a stable order."""
    rows: list[dict[str, Any]] = []
    for (config, language, snr), outcomes in group(results).items():
        summary = summarize(outcomes)
        if summary is None:
            continue
        songs = {
            result.song
            for result in results
            if (result.config, result.language, result.snr_db) == (config, language, snr)
        }
        rows.append(
            {
                "config": config,
                "language": language,
                "snr_db": snr,
                "songs": len(songs),
                **summary.to_dict(),
            }
        )
    return rows


def _row(summary: Summary) -> str:
    return (
        f"{summary.tokens} | {_fmt(summary.median_ms)} | {_fmt(summary.p90_ms)} | "
        f"{_fmt(summary.p95_ms)} | {_fmt(summary.needs_fix_pct, 1)}% | "
        f"{_fmt(summary.line_mismatch_pct, 1)}% | {summary.bias_ms:+.0f}"
    )


_HEAD = "tokens | median ms | P90 ms | P95 ms | >150 ms | wrong line | bias ms"
_RULE = "---: | ---: | ---: | ---: | ---: | ---: | ---:"


def _check(label: str, value: float | None, limit: float) -> str:
    if value is None:
        return f"| {label} | ≤ {limit:g} | – | 無資料 |"
    verdict = "達成" if value <= limit else "**未達成**"
    return f"| {label} | ≤ {limit:g} | {value:.1f} | {verdict} |"


def target_table(results: Sequence[RunResult], config: str, anchor_config: str | None) -> list[str]:
    """Comparison with the SPEC §10.4 targets for Chinese at 10 dB."""
    pooled = group(results)
    base = summarize(pooled.get((config, "zh", 10), []))
    anchored = summarize(pooled.get((anchor_config, "zh", 10), [])) if anchor_config else None
    lines = [
        f"設定:`{config}`,中文,10 dB" + (f"(共 {base.tokens} 個 token)" if base else ""),
        "",
        "| 指標 | 目標 | 實測 | 結果 |",
        "|---|---:|---:|---|",
        _check("起始時間誤差中位數 (ms)", base.median_ms if base else None, TARGETS["median_ms"]),
        _check("起始時間誤差 P95 (ms)", base.p95_ms if base else None, TARGETS["p95_ms"]),
        _check(
            f"需人工修正比例(誤差 > {FIX_THRESHOLD_MS} ms,%)",
            base.needs_fix_pct if base else None,
            TARGETS["needs_fix_pct"],
        ),
        _check(
            "隨機 lock 5% 錨點後的需人工修正比例(%)",
            anchored.needs_fix_pct if anchored else None,
            TARGETS["needs_fix_after_anchors_pct"],
        ),
    ]
    return lines


def anchor_effects(results: Sequence[RunResult], main_config: str) -> list[dict[str, Any]]:
    """What locking the anchors did to the *other* tokens, token by token.

    The accuracy tables compare two different sets of tokens (the anchors are left out of
    the anchored runs).  Here every unlocked token of an anchored run is paired with the same
    token of the main configuration, which answers the question the anchor experiment is
    about: did the user's corrections make the rest better or worse?

    Returns:
        One row per anchored configuration and language (plus ``all``): the number of
        paired tokens, the share needing a fix before and after, and how many tokens went
        from wrong to right (``fixed``) and from right to wrong (``broken``).
    """
    base = {
        (result.item, outcome.line, outcome.index): outcome
        for result in results
        if result.config == main_config
        for outcome in result.outcomes
    }
    rows: list[dict[str, Any]] = []
    anchored = [
        config
        for config in dict.fromkeys(result.config for result in results)
        if any(result.anchors for result in results if result.config == config)
    ]
    languages = list(dict.fromkeys(result.language for result in results))
    for config in anchored:
        for language in [*languages, "all"]:
            tokens = before = after = fixed = broken = 0
            for result in results:
                if result.config != config or language not in ("all", result.language):
                    continue
                for outcome in result.outcomes:
                    reference = base.get((result.item, outcome.line, outcome.index))
                    if outcome.locked or reference is None:
                        continue
                    was_wrong = reference.start_error_ms > FIX_THRESHOLD_MS
                    is_wrong = outcome.start_error_ms > FIX_THRESHOLD_MS
                    tokens += 1
                    before += was_wrong
                    after += is_wrong
                    fixed += was_wrong and not is_wrong
                    broken += is_wrong and not was_wrong
            if tokens:
                rows.append(
                    {
                        "config": config,
                        "language": language,
                        "tokens": tokens,
                        "needs_fix_before_pct": 100.0 * before / tokens,
                        "needs_fix_after_pct": 100.0 * after / tokens,
                        "fixed": fixed,
                        "broken": broken,
                    }
                )
    return rows


def timing_rows(results: Sequence[RunResult]) -> list[dict[str, Any]]:
    """Mean compute time per stage, normalised to one minute of audio, per configuration."""
    rows: list[dict[str, Any]] = []
    for config in dict.fromkeys(result.config for result in results):
        chosen = [result for result in results if result.config == config]
        audio = sum(result.audio_seconds for result in chosen)
        if audio <= 0:
            continue
        per_stage = {
            stage: 60.0 * sum(result.stage_seconds.get(stage, 0.0) for result in chosen) / audio
            for stage in PROCESS_STAGES
        }
        total = sum(per_stage.values())
        rows.append(
            {
                "config": config,
                "runs": len(chosen),
                "seconds_per_audio_minute": per_stage,
                "total_seconds_per_audio_minute": total,
                "realtime_factor": 60.0 / total if total > 0 else None,
            }
        )
    return rows


def build_report(
    results: Sequence[RunResult],
    *,
    title: str,
    main_config: str,
    anchor_config: str | None = None,
    notes: Sequence[str] = (),
    environment: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Create the Markdown report and the JSON document for a benchmark run.

    Args:
        results: Every run of the matrix.
        title: Report title.
        main_config: Configuration that the SPEC targets apply to.
        anchor_config: Configuration of the random-anchor experiment, if it was run.
        notes: Free-form remarks placed at the top of the report.
        environment: Machine description to record (CPU, threads, …).
    """
    rows = summaries(results)
    pooled = group(results)
    configs = list(dict.fromkeys(result.config for result in results))
    languages = list(dict.fromkeys(result.language for result in results))
    snr_levels = sorted({result.snr_db for result in results}, key=lambda v: (v is None, v or 0))
    env = {
        "karaforge": __version__,
        "python": platform.python_version(),
        "machine": platform.processor() or platform.machine(),
        **(environment or {}),
    }
    out: list[str] = [f"# {title}", ""]
    out.append(f"產生時間:{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    out.append("")
    out += [f"- {key}: {value}" for key, value in env.items()]
    out.append("")
    out += [f"> {note}" for note in notes]
    if notes:
        out.append("")

    if any(key == (main_config, "zh", 10) for key in pooled):
        out += [
            "## 與規格 §10.4 目標對照",
            "",
            *target_table(results, main_config, anchor_config),
            "",
        ]

    out += ["## 各設定的對齊準確度", ""]
    for language in languages:
        for snr in snr_levels:
            present = [config for config in configs if (config, language, snr) in pooled]
            if not present:
                continue
            out += [f"### {language},{_snr(snr)}", "", f"| 設定 | {_HEAD} |", f"|---| {_RULE} |"]
            for config in present:
                summary = summarize(pooled[(config, language, snr)])
                if summary is not None:
                    out.append(f"| `{config}` | {_row(summary)} |")
            out.append("")

    effects = anchor_effects(results, main_config)
    if effects:
        out += [
            "## 錨點對其餘 token 的影響(同一批 token,鎖定前 → 鎖定後)",
            "",
            f"每一列把錨點實驗裡沒有被鎖定的 token,與 `{main_config}`(沒有錨點)"
            "裡的同一個 token 配對;"
            f"「需修正」指起始時間誤差超過 {FIX_THRESHOLD_MS} ms。"
            "「修好」是鎖定錨點後從需修正變成不需修正的 token 數,「弄壞」是反過來。",
            "",
            "| 設定 | 語言 | tokens | 鎖定前需修正 | 鎖定後需修正 | 修好 | 弄壞 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        out += [
            f"| `{row['config']}` | {row['language']} | {row['tokens']} | "
            f"{row['needs_fix_before_pct']:.1f}% | {row['needs_fix_after_pct']:.1f}% | "
            f"{row['fixed']} | {row['broken']} |"
            for row in effects
        ]
        out.append("")

    out += [
        "## 結束時間(行尾長音)與信心度",
        "",
        "| 設定 | 語言 | SNR | 行尾結束誤差中位數 ms | 行尾結束誤差 P90 ms | 信心度 AUROC | "
        "檢查信心最低 10% 找到的問題比例 | 20% |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        recall_10 = None if row["recall_at_10_pct"] is None else 100 * row["recall_at_10_pct"]
        recall_20 = None if row["recall_at_20_pct"] is None else 100 * row["recall_at_20_pct"]
        out.append(
            f"| `{row['config']}` | {row['language']} | {_snr(row['snr_db'])} | "
            f"{_fmt(row['line_end_median_ms'])} | {_fmt(row['line_end_p90_ms'])} | "
            f"{_fmt(row['confidence_auroc'], 2)} | {_fmt(recall_10)}% | {_fmt(recall_20)}% |"
        )
    out.append("")

    timings = timing_rows(results)
    out += [
        "## 處理時間(每分鐘音訊所需秒數,CPU)",
        "",
        "| 設定 | " + " | ".join(PROCESS_STAGES) + " | 合計 | 即時倍率 |",
        "|---|" + " ---: |" * (len(PROCESS_STAGES) + 2),
    ]
    for timing in timings:
        cells = " | ".join(
            f"{timing['seconds_per_audio_minute'][stage]:.1f}" for stage in PROCESS_STAGES
        )
        factor = timing["realtime_factor"]
        out.append(
            f"| `{timing['config']}` | {cells} | {timing['total_seconds_per_audio_minute']:.1f} | "
            f"{'–' if factor is None else f'{factor:.1f}x'} |"
        )
    out.append("")
    out.append(
        "時間是各階段「實際計算」時記錄下來的秒數;同一首歌的後續設定會沿用分離與辨識的快取,"
        "但表中仍列出該階段原本的計算時間。"
    )
    out.append("")

    document = {
        "title": title,
        "environment": env,
        "main_config": main_config,
        "anchor_config": anchor_config,
        "targets": TARGETS,
        "notes": list(notes),
        "summaries": rows,
        "anchor_effects": effects,
        "timing": timings,
        "runs": [
            {
                "item": result.item,
                "song": result.song,
                "language": result.language,
                "snr_db": result.snr_db,
                "config": result.config,
                "anchors": result.anchors,
                "audio_seconds": result.audio_seconds,
                "stage_seconds": result.stage_seconds,
                "windows_from": result.windows_from,
                "summary": (s.to_dict() if (s := summarize(result.outcomes)) else None),
            }
            for result in results
        ],
    }
    return "\n".join(out) + "\n", document


def per_song_medians(results: Sequence[RunResult], config: str) -> dict[str, float]:
    """Median start error of each item for one configuration (to spot outlier songs)."""
    return {
        result.item: float(np.median([o.start_error_ms for o in result.outcomes if not o.locked]))
        for result in results
        if result.config == config and any(not o.locked for o in result.outcomes)
    }
