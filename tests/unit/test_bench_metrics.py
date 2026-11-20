from __future__ import annotations

import json
from pathlib import Path

import pytest

from karaforge.project import Line, Project, Token
from kfbench.cli import build_configs
from kfbench.metrics import (
    TokenOutcome,
    auroc,
    interval_distance,
    recall_at,
    summarize,
    wrong_line,
)
from kfbench.report import TARGETS, anchor_effects, build_report, per_song_medians, timing_rows
from kfbench.runner import (
    RunResult,
    choose_anchors,
    collect_outcomes,
    load_truth,
)


def outcome(
    error: int,
    *,
    confidence: float = 0.9,
    locked: bool = False,
    final: bool = False,
    wrong: bool = False,
    end_error: int = 0,
    line: int = 0,
    index: int = 0,
) -> TokenOutcome:
    return TokenOutcome(
        song="s",
        line=line,
        index=index,
        text="字",
        true_start_ms=10_000,
        true_end_ms=10_400,
        pred_start_ms=10_000 + error,
        pred_end_ms=10_400 + end_error,
        confidence=confidence,
        locked=locked,
        line_final=final,
        wrong_line=wrong,
    )


def test_summary_statistics() -> None:
    errors = [0, 10, -20, 30, 40, -50, 60, 70, 200, -400]
    summary = summarize([outcome(error) for error in errors])
    assert summary is not None
    assert summary.tokens == 10
    assert summary.median_ms == pytest.approx(45.0)
    assert summary.mean_ms == pytest.approx(88.0)
    assert summary.p90_ms == pytest.approx(220.0)
    assert summary.p95_ms == pytest.approx(310.0)
    assert summary.needs_fix_pct == pytest.approx(20.0)
    assert summary.bias_ms == pytest.approx(20.0)


def test_locked_tokens_are_excluded() -> None:
    summary = summarize([outcome(0, locked=True), outcome(100), outcome(300)])
    assert summary is not None
    assert summary.tokens == 2
    assert summary.needs_fix_pct == pytest.approx(50.0)
    assert summarize([outcome(0, locked=True)]) is None
    assert summarize([]) is None


def test_end_errors_and_line_final_tokens() -> None:
    summary = summarize(
        [
            outcome(0, end_error=50),
            outcome(0, end_error=900, final=True),
            outcome(0, end_error=-100, final=True),
        ]
    )
    assert summary is not None
    assert summary.end_median_ms == pytest.approx(100.0)
    assert summary.line_end_median_ms == pytest.approx(500.0)
    assert summary.line_end_p90_ms == pytest.approx(820.0)


def test_wrong_line_definition() -> None:
    spans = [(1000, 3000), (4000, 6000), (10_000, 12_000)]
    assert interval_distance(500, 1000, 3000) == 500
    assert interval_distance(2000, 1000, 3000) == 0
    assert interval_distance(3500, 1000, 3000) == 500
    assert wrong_line(2000, 0, spans) is False
    assert wrong_line(3400, 0, spans) is False  # 400 ms after its line, 600 ms before the next
    assert wrong_line(3600, 0, spans) is True
    assert wrong_line(5000, 0, spans) is True
    assert wrong_line(3500, 0, spans) is False  # a tie stays with its own line
    summary = summarize([outcome(0, wrong=True), outcome(0), outcome(0), outcome(0)])
    assert summary is not None and summary.line_mismatch_pct == pytest.approx(25.0)


def test_auroc_and_recall() -> None:
    assert auroc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == pytest.approx(1.0)
    assert auroc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == pytest.approx(0.0)
    assert auroc([0.5, 0.5, 0.5, 0.5], [True, False, True, False]) == pytest.approx(0.5)
    assert auroc([0.9, 0.4, 0.6, 0.1], [True, True, False, False]) == pytest.approx(0.75)
    assert auroc([0.1, 0.2], [True, True]) is None
    assert auroc([], []) is None
    scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
    bad = [True, False, True, False, False, False, False, False, False, True]
    assert recall_at(scores, bad, 0.1) == pytest.approx(1 / 3)
    assert recall_at(scores, bad, 0.3) == pytest.approx(2 / 3)
    assert recall_at(scores, [False] * 10, 0.5) is None


def test_confidence_metrics_in_summary() -> None:
    tokens = [outcome(300, confidence=0.1), outcome(0, confidence=0.9), outcome(10, confidence=0.8)]
    summary = summarize(tokens)
    assert summary is not None
    assert summary.confidence_auroc == pytest.approx(1.0)
    assert summary.recall_at_10_pct == pytest.approx(1.0)


def truth_file(tmp_path: Path) -> Path:
    path = tmp_path / "truth.json"
    path.write_text(
        json.dumps(
            {
                "lines": [
                    {
                        "tokens": [
                            {"text": "一", "start_ms": 1000, "end_ms": 1400},
                            {"text": "二", "start_ms": 1400, "end_ms": 2000},
                        ]
                    },
                    {"tokens": [{"text": "三", "start_ms": 5000, "end_ms": 5600}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_collect_outcomes_pairs_prediction_and_truth(tmp_path: Path) -> None:
    truth = load_truth(truth_file(tmp_path))
    project = Project(
        lines=[
            Line(
                id="L001",
                tokens=[
                    Token(text="一", start_ms=1030, end_ms=1400, confidence=0.7),
                    Token(text="二", start_ms=4900, end_ms=5000, confidence=0.2),
                ],
            ),
            Line(id="L002"),
            Line(
                id="L003",
                tokens=[Token(text="三", start_ms=5000, end_ms=5500, locked=True, source="manual")],
            ),
        ]
    )
    outcomes = collect_outcomes(project, truth, "demo")
    assert [(o.line, o.index, o.start_error_ms, o.line_final) for o in outcomes] == [
        (0, 0, 30, False),
        (0, 1, 3500, True),
        (1, 0, 0, True),
    ]
    assert [o.wrong_line for o in outcomes] == [False, True, False]
    assert outcomes[2].locked and outcomes[2].end_error_ms == 100
    assert outcomes[0].confidence == 0.7


def test_collect_outcomes_rejects_mismatched_or_untimed_projects(tmp_path: Path) -> None:
    truth = load_truth(truth_file(tmp_path))
    with pytest.raises(ValueError, match="lines"):
        collect_outcomes(Project(), truth, "demo")
    short = Project(
        lines=[
            Line(id="L001", tokens=[Token(text="一", start_ms=0, end_ms=1)]),
            Line(id="L002", tokens=[Token(text="三", start_ms=0, end_ms=1)]),
        ]
    )
    with pytest.raises(ValueError, match="token count"):
        collect_outcomes(short, truth, "demo")
    untimed = Project(
        lines=[
            Line(id="L001", tokens=[Token(text="一"), Token(text="二")]),
            Line(id="L002", tokens=[Token(text="三")]),
        ]
    )
    with pytest.raises(ValueError, match="not aligned"):
        collect_outcomes(untimed, truth, "demo")


def test_choose_anchors() -> None:
    outcomes = [
        outcome(0, confidence=1 - index / 100, line=index // 10, index=index % 10)
        for index in range(100)
    ]
    random_a = choose_anchors(outcomes, "random", 0.05, "song/config")
    assert len(random_a) == 5 and len(set(random_a)) == 5
    assert random_a == choose_anchors(outcomes, "random", 0.05, "song/config")
    assert random_a != choose_anchors(outcomes, "random", 0.05, "other-song/config")
    lowest = choose_anchors(outcomes, "low-confidence", 0.05, "x")
    assert sorted(lowest) == [(9, 5), (9, 6), (9, 7), (9, 8), (9, 9)]
    assert len(choose_anchors(outcomes[:3], "random", 0.05, "x")) == 1


def test_build_configs_expands_aligners_ablation_and_anchors() -> None:
    configs, main, anchor = build_configs("balanced", [], {}, ablation=False, anchors=False)
    assert [config.name for config in configs] == ["balanced"]
    assert (main, anchor) == ("balanced", None)
    assert configs[0].overrides == {}

    configs, main, anchor = build_configs(
        "balanced",
        ["ctc", "whisper-attn", "hybrid", "whisper-attn"],
        {"align.onset_snap_ms": 80},
        ablation=True,
        anchors=True,
    )
    names = [config.name for config in configs]
    # ``ctc`` is the profile's own aligner: it is the main configuration, not a comparison.
    assert names == [
        "balanced",
        "balanced / no-coarse(regions)",
        "balanced / no-coarse(global)",
        "balanced / no-onset-snap",
        "balanced / no-weak-rescue",
        "balanced / no-long-note",
        "balanced / anchors-random-5%",
        "balanced / anchors-lowconf-5%",
        "balanced / anchors-random-5% (v7 handling)",
        "balanced+whisper-attn",
        "balanced+hybrid",
    ]
    assert (main, anchor) == ("balanced", "balanced / anchors-random-5%")
    by_name = {config.name: config for config in configs}
    # The comparison with the old anchor handling locks the very same tokens.
    cut = by_name["balanced / anchors-random-5% (v7 handling)"]
    assert cut.overrides["align.anchor_context"] is False
    assert cut.anchor_seed == "balanced / anchors-random-5%" and cut.anchors == "random"
    assert by_name["balanced / anchors-random-5%"].anchor_seed is None
    ablated = by_name["balanced / no-onset-snap"].overrides
    assert ablated == {"align.onset_snap_ms": 80, "align.onset_snap": False}
    assert by_name["balanced / no-weak-rescue"].overrides["align.weak_score"] == 0
    assert by_name["balanced / anchors-random-5%"].anchors == "random"
    assert by_name["balanced / anchors-lowconf-5%"].anchors == "low-confidence"
    compared = by_name["balanced+whisper-attn"].overrides
    assert compared["align.aligner"] == "whisper-attn" and compared["align.onset_snap_ms"] == 80
    # The single-pass ablation only exists for aligners that can take a whole song.
    configs, main, _anchor = build_configs("cpu-lite", ["ctc"], {}, ablation=True, anchors=False)
    assert main == "cpu-lite"
    assert not any("global" in config.name for config in configs)
    assert configs[-1].name == "cpu-lite+ctc"


def run(
    config: str,
    errors: list[int],
    *,
    language: str = "zh",
    snr: int | None = 10,
    song: str = "zh-1000",
    locked: int = 0,
) -> RunResult:
    outcomes = [
        outcome(error, final=index == len(errors) - 1) for index, error in enumerate(errors)
    ]
    outcomes += [outcome(0, locked=True) for _ in range(locked)]
    return RunResult(
        item=f"{song}-snr{snr}",
        song=song,
        language=language,
        snr_db=snr,
        config=config,
        outcomes=outcomes,
        stage_seconds={"ingest": 1.0, "separate": 20.0, "analyze": 2.0, "asr": 5.0, "align": 2.0},
        audio_seconds=60.0,
        windows_from={"asr": 4},
        anchors=locked,
    )


def test_report_compares_with_targets_and_lists_every_group() -> None:
    results = [
        run("balanced", [10, 20, 30, 40, 400]),
        run("balanced", [5, 15, 25], song="zh-1001"),
        run("balanced", [50, 60], language="en", song="en-1000"),
        run("balanced", [70, 80], snr=0),
        run("balanced / anchors-random-5%", [10, 20, 30, 40], locked=1),
    ]
    markdown, document = build_report(
        results,
        title="測試報告",
        main_config="balanced",
        anchor_config="balanced / anchors-random-5%",
        notes=["備註"],
    )
    assert markdown.startswith("# 測試報告\n")
    assert "> 備註" in markdown
    assert "## 與規格 §10.4 目標對照" in markdown
    assert "| 起始時間誤差中位數 (ms) | ≤ 60 | 22.5 | 達成 |" in markdown
    assert "| 起始時間誤差 P95 (ms) | ≤ 250 | 274.0 | **未達成** |" in markdown
    assert "| 需人工修正比例(誤差 > 150 ms,%) | ≤ 10 | 12.5 | **未達成** |" in markdown
    assert "| 隨機 lock 5% 錨點後的需人工修正比例(%) | ≤ 5 | 0.0 | 達成 |" in markdown
    assert "### zh,10 dB" in markdown and "### en,10 dB" in markdown and "### zh,0 dB" in markdown
    assert "| `balanced` | 8 | 22 | 148 | 274 | 12.5% | 0.0% | +22 |" in markdown
    assert document["targets"] == TARGETS
    assert len(document["runs"]) == 5
    zh = next(
        row
        for row in document["summaries"]
        if (row["config"], row["language"], row["snr_db"]) == ("balanced", "zh", 10)
    )
    assert zh["songs"] == 2 and zh["tokens"] == 8
    assert json.dumps(document, ensure_ascii=False)


def test_anchor_effects_pair_the_same_tokens_before_and_after() -> None:
    def result(config: str, errors: list[int], locked: frozenset[int] = frozenset()) -> RunResult:
        return RunResult(
            item="zh-1000-snr10",
            song="zh-1000",
            language="zh",
            snr_db=10,
            config=config,
            outcomes=[
                outcome(error, index=index, locked=index in locked)
                for index, error in enumerate(errors)
            ],
            stage_seconds={},
            audio_seconds=60.0,
            windows_from={},
            anchors=len(locked),
        )

    results = [
        result("balanced", [10, 300, 20, 400, 30, 40]),
        # Token 1 is the anchor (set to the truth).  Of the others, token 3 is now right and
        # token 4 is now wrong.
        result("balanced / anchors-random-5%", [10, 0, 20, 50, 500, 40], frozenset({1})),
        result("balanced+other", [10, 10, 10, 10, 10, 10]),
    ]
    rows = anchor_effects(results, "balanced")
    assert [(row["config"], row["language"]) for row in rows] == [
        ("balanced / anchors-random-5%", "zh"),
        ("balanced / anchors-random-5%", "all"),
    ]
    assert rows[0] == {
        "config": "balanced / anchors-random-5%",
        "language": "zh",
        "tokens": 5,  # the anchor itself is not counted
        "needs_fix_before_pct": 20.0,  # token 3, in the run without anchors
        "needs_fix_after_pct": 20.0,  # token 4, after locking
        "fixed": 1,
        "broken": 1,
    }
    markdown, document = build_report(results, title="t", main_config="balanced")
    assert "## 錨點對其餘 token 的影響" in markdown
    assert "| `balanced / anchors-random-5%` | zh | 5 | 20.0% | 20.0% | 1 | 1 |" in markdown
    assert document["anchor_effects"] == rows
    # A run without an anchor experiment has no such section.
    markdown, document = build_report(results[:1], title="t", main_config="balanced")
    assert "錨點對其餘" not in markdown and document["anchor_effects"] == []


def test_report_without_the_target_group_has_no_target_section() -> None:
    markdown, _document = build_report(
        [run("balanced", [10, 20], language="en", song="en-1000")],
        title="t",
        main_config="balanced",
    )
    assert "§10.4" not in markdown


def test_timing_is_normalised_per_minute_of_audio() -> None:
    rows = timing_rows([run("balanced", [1]), run("balanced", [2], song="zh-1001")])
    assert len(rows) == 1
    assert rows[0]["seconds_per_audio_minute"]["separate"] == pytest.approx(20.0)
    assert rows[0]["total_seconds_per_audio_minute"] == pytest.approx(30.0)
    assert rows[0]["realtime_factor"] == pytest.approx(2.0)
    assert run("balanced", [1]).realtime_factor == pytest.approx(2.0)
    assert per_song_medians([run("balanced", [10, 30, 50])], "balanced") == {"zh-1000-snr10": 30.0}
