"""CTC forced alignment (Viterbi) in plain numpy.

A CTC acoustic model outputs, for every 20 ms frame, a probability for each symbol of its
vocabulary plus a *blank*.  Forced alignment finds the most probable way to lay a known
symbol sequence over the frames: each symbol occupies one or more consecutive frames, blanks
may sit between symbols, and two identical neighbouring symbols must be separated by a blank.

The functions here work on an *emission matrix* whose columns are exactly the symbols the
caller needs (not the model's whole vocabulary).  That lets a column be anything that behaves
like a log-probability — a pooled class of homophones, or the **wildcard** column used for
sound that is not part of the text (the tail of the previous line inside a padded window, or
a word the model has no symbols for).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import numpy.typing as npt

F32 = npt.NDArray[np.float32]

NEG_INF = np.float32(-1e30)


@dataclass(frozen=True)
class CtcSpan:
    """Frames assigned to one target symbol."""

    start_frame: int
    end_frame: int
    """One past the last frame."""
    score: float
    """Mean probability of the symbol over its frames, in ``[0, 1]``."""


def min_frames(targets: Sequence[int]) -> int:
    """Fewest frames that can hold ``targets``: one each, plus a blank between equal neighbours."""
    repeats = sum(1 for first, second in pairwise(targets) if first == second)
    return len(targets) + repeats


def forced_align(
    emissions: F32, targets: Sequence[int], blank: int | Sequence[int] = 0
) -> list[CtcSpan] | None:
    """Align ``targets`` to ``emissions`` with the Viterbi algorithm.

    Args:
        emissions: Log-probabilities of shape ``(frames, columns)``.
        targets: Column index of each target symbol, in order.  Must not contain ``blank``.
        blank: Column index of the blank symbol.  A sequence gives every gap its own blank
            column — ``len(targets) + 1`` entries: before each target and after the last —
            which lets a caller combine the outputs of two acoustic models, each with its
            own notion of "nothing here".

    Returns:
        One span per target (non-overlapping, in order), or ``None`` when the sequence
        cannot fit into the given number of frames.
    """
    frames = int(emissions.shape[0])
    count = len(targets)
    if count == 0:
        return []
    if frames < min_frames(targets):
        return None

    # Extended sequence: blank, t1, blank, t2, …, blank.
    states = 2 * count + 1
    extended = np.empty(states, dtype=np.int64)
    if isinstance(blank, int):
        extended[0::2] = blank
    else:
        if len(blank) != count + 1:
            raise ValueError("one blank column is needed before each target and after the last")
        extended[0::2] = np.asarray(blank, dtype=np.int64)
    extended[1::2] = np.asarray(targets, dtype=np.int64)
    # From state s one may come from s (stay), s-1 (advance) or, between two *different*
    # symbols, s-2 (skip the blank).
    can_skip = np.zeros(states, dtype=np.bool_)
    can_skip[3::2] = extended[3::2] != extended[1:-2:2]

    score = np.full(states, NEG_INF, dtype=np.float32)
    score[0] = emissions[0, extended[0]]
    score[1] = emissions[0, extended[1]]
    back = np.zeros((frames, states), dtype=np.uint8)

    advance = np.empty(states, dtype=np.float32)
    skip = np.empty(states, dtype=np.float32)
    for frame in range(1, frames):
        advance[0] = NEG_INF
        advance[1:] = score[:-1]
        skip[:2] = NEG_INF
        skip[2:] = score[:-2]
        skip[~can_skip] = NEG_INF
        best = score
        choice = np.zeros(states, dtype=np.uint8)
        better = advance > best
        best = np.where(better, advance, best)
        choice[better] = 1
        better = skip > best
        best = np.where(better, skip, best)
        choice[better] = 2
        back[frame] = choice
        score = (best + emissions[frame, extended]).astype(np.float32)

    # The path may end in the last symbol or in the final blank.
    state = states - 1 if score[states - 1] >= score[states - 2] else states - 2
    if score[state] <= NEG_INF / 2:
        return None
    path = np.empty(frames, dtype=np.int64)
    for frame in range(frames - 1, -1, -1):
        path[frame] = state
        state -= int(back[frame, state])

    spans: list[CtcSpan] = []
    for index in range(count):
        occupied = np.flatnonzero(path == 2 * index + 1)
        if occupied.size == 0:
            return None
        start, end = int(occupied[0]), int(occupied[-1]) + 1
        probability = float(np.exp(emissions[start:end, targets[index]].astype(np.float64)).mean())
        spans.append(CtcSpan(start, end, min(1.0, max(0.0, probability))))
    return spans


def log_softmax(logits: F32) -> F32:
    """Row-wise log-softmax."""
    shifted = logits - logits.max(axis=1, keepdims=True)
    return (shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))).astype(np.float32)


def pooled_column(log_probs: F32, columns: Sequence[int]) -> F32:
    """Log of the summed probability of several columns (e.g. all homophones of a syllable)."""
    if len(columns) == 1:
        return log_probs[:, columns[0]]
    selected = log_probs[:, list(columns)].astype(np.float64)
    peak = selected.max(axis=1, keepdims=True)
    return (peak[:, 0] + np.log(np.exp(selected - peak).sum(axis=1))).astype(np.float32)


def wildcard_column(blank_log_probs: F32, penalty: float = 0.1) -> F32:
    """Log-probability that a frame holds *some* non-blank symbol, slightly penalised.

    Used for sound that is not in the text.  The small penalty makes a real symbol win a tie,
    so the wildcard never eats frames that the text itself explains equally well.

    Args:
        blank_log_probs: Log-probability of "nothing here" per frame (the blank, plus any
            other symbol that carries no sound, pooled by the caller).
        penalty: Subtracted from the result.
    """
    blank_probability = np.exp(blank_log_probs.astype(np.float64))
    other = np.log(np.clip(1.0 - blank_probability, 1e-9, 1.0))
    return (other - penalty).astype(np.float32)
