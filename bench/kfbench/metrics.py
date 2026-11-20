"""Benchmark metrics: how far predicted token times are from the ground truth.

Definitions (also in ``docs/benchmark.md``):

* **Start error** of a token — ``|predicted start − true start|`` in milliseconds.
* **Needs fixing** — a token whose start error exceeds :data:`FIX_THRESHOLD_MS` (150 ms): the
  share of such tokens estimates how many tokens a user would have to correct by hand.
* **Line mismatch** — a token whose predicted start is closer to the time span of *another*
  line than to that of its own line.
* **End error** — the same as the start error for end times; reported separately for the last
  token of each line, which is what the long-note handling is responsible for.
* **Confidence AUROC** — how well ``1 − confidence`` ranks the tokens that need fixing above
  the ones that do not (0.5 = useless, 1.0 = perfect).
* **Recall at k %** — the share of the tokens that need fixing which a user finds by checking
  only the k % of tokens with the lowest confidence.

Locked tokens (set to the truth in the anchor experiment) are excluded everywhere: they would
count as perfect predictions that the system did not make.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass

import numpy as np

FIX_THRESHOLD_MS = 150


@dataclass(frozen=True)
class TokenOutcome:
    """Prediction and truth for one token."""

    song: str
    line: int
    index: int
    text: str
    true_start_ms: int
    true_end_ms: int
    pred_start_ms: int
    pred_end_ms: int
    confidence: float
    locked: bool
    line_final: bool
    wrong_line: bool

    @property
    def start_error_ms(self) -> int:
        """Absolute start-time error."""
        return abs(self.pred_start_ms - self.true_start_ms)

    @property
    def signed_start_error_ms(self) -> int:
        """Predicted minus true start (positive = late)."""
        return self.pred_start_ms - self.true_start_ms

    @property
    def end_error_ms(self) -> int:
        """Absolute end-time error."""
        return abs(self.pred_end_ms - self.true_end_ms)


@dataclass(frozen=True)
class Summary:
    """Aggregate metrics over a set of tokens."""

    tokens: int
    median_ms: float
    mean_ms: float
    p90_ms: float
    p95_ms: float
    bias_ms: float
    """Median signed error: positive when predictions are late."""
    needs_fix_pct: float
    line_mismatch_pct: float
    end_median_ms: float
    line_end_median_ms: float
    line_end_p90_ms: float
    confidence_auroc: float | None
    recall_at_10_pct: float | None
    recall_at_20_pct: float | None

    def to_dict(self) -> dict[str, float | int | None]:
        """The summary as a JSON-serialisable mapping."""
        return asdict(self)


def interval_distance(time_ms: float, start_ms: float, end_ms: float) -> float:
    """Distance from a time to an interval (zero inside it)."""
    if time_ms < start_ms:
        return start_ms - time_ms
    if time_ms > end_ms:
        return time_ms - end_ms
    return 0.0


def wrong_line(pred_start_ms: int, own: int, spans: Sequence[tuple[int, int]]) -> bool:
    """Whether a predicted start is closer to another line's true span than to its own."""
    own_distance = interval_distance(pred_start_ms, *spans[own])
    return any(
        interval_distance(pred_start_ms, *span) < own_distance
        for index, span in enumerate(spans)
        if index != own
    )


def auroc(scores: Sequence[float], positives: Sequence[bool]) -> float | None:
    """Area under the ROC curve of ``scores`` for detecting ``positives`` (ties count half)."""
    values = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(positives, dtype=np.bool_)
    positive_count = int(labels.sum())
    negative_count = int(labels.size - positive_count)
    if positive_count == 0 or negative_count == 0:
        return None
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    sorted_values = values[order]
    start = 0
    while start < values.size:
        end = start
        while end + 1 < values.size and sorted_values[end + 1] == sorted_values[start]:
            end += 1
        ranks[order[start : end + 1]] = (start + end) / 2.0 + 1.0
        start = end + 1
    rank_sum = float(ranks[labels].sum())
    return (rank_sum - positive_count * (positive_count + 1) / 2.0) / (
        positive_count * negative_count
    )


def recall_at(scores: Sequence[float], positives: Sequence[bool], share: float) -> float | None:
    """Share of positives among the ``share`` highest-scoring items, relative to all positives."""
    labels = np.asarray(positives, dtype=np.bool_)
    total = int(labels.sum())
    if total == 0 or labels.size == 0:
        return None
    budget = max(1, round(labels.size * share))
    order = np.argsort(-np.asarray(scores, dtype=np.float64), kind="mergesort")
    return float(labels[order[:budget]].sum() / total)


def summarize(outcomes: Iterable[TokenOutcome]) -> Summary | None:
    """Aggregate token outcomes (locked tokens are ignored).  ``None`` when nothing is left."""
    tokens = [outcome for outcome in outcomes if not outcome.locked]
    if not tokens:
        return None
    errors = np.asarray([token.start_error_ms for token in tokens], dtype=np.float64)
    signed = np.asarray([token.signed_start_error_ms for token in tokens], dtype=np.float64)
    end_errors = np.asarray([token.end_error_ms for token in tokens], dtype=np.float64)
    final_end = np.asarray(
        [token.end_error_ms for token in tokens if token.line_final], dtype=np.float64
    )
    bad = [token.start_error_ms > FIX_THRESHOLD_MS for token in tokens]
    doubt = [1.0 - token.confidence for token in tokens]
    return Summary(
        tokens=len(tokens),
        median_ms=float(np.median(errors)),
        mean_ms=float(errors.mean()),
        p90_ms=float(np.percentile(errors, 90)),
        p95_ms=float(np.percentile(errors, 95)),
        bias_ms=float(np.median(signed)),
        needs_fix_pct=100.0 * float(np.mean(bad)),
        line_mismatch_pct=100.0 * float(np.mean([token.wrong_line for token in tokens])),
        end_median_ms=float(np.median(end_errors)),
        line_end_median_ms=float(np.median(final_end)) if final_end.size else 0.0,
        line_end_p90_ms=float(np.percentile(final_end, 90)) if final_end.size else 0.0,
        confidence_auroc=auroc(doubt, bad),
        recall_at_10_pct=recall_at(doubt, bad, 0.10),
        recall_at_20_pct=recall_at(doubt, bad, 0.20),
    )
