"""Confidence scoring: how much should the user trust each token's timing?

Three independent pieces of evidence are combined into one number in ``[0, 1]``:

* the **aligner's own score** for the token;
* **agreement between the coarse and the fine pass** — whether the final start is close to
  where the speech recogniser heard the token, and how well the line as a whole matched;
* the **onset match** — whether the final start sits on a detected vocal onset.

Tokens whose time had to be interpolated get a low fixed score, and locked tokens are 1.0 by
definition.  The editor colours tokens by this value so that attention goes to the doubtful
ones first.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from karaforge.align.coarse import LineWindow
from karaforge.align.refine import RefinedToken

WEIGHT_ALIGNER = 0.4
WEIGHT_COARSE = 0.35
WEIGHT_ONSET = 0.25
_ESTIMATED_CONFIDENCE = 0.1


def coarse_agreement(token: RefinedToken, hint: float | None, window: LineWindow) -> float:
    """Evidence from the coarse pass for one token, in ``[0, 1]``."""
    if hint is not None:
        # Full credit within 150 ms of where the recogniser heard it, fading out by ~1 s.
        distance = abs(token.start_s - hint)
        closeness = math.exp(-max(0.0, distance - 0.15) / 0.3)
        return 0.3 * window.quality + 0.7 * closeness
    if window.source == "anchor":
        return 0.8
    if window.source == "hint":
        return 0.6
    if window.source == "asr":
        return 0.5 * window.quality
    return 0.15 if window.source == "regions" else 0.05


def onset_agreement(token: RefinedToken) -> float:
    """Evidence from the onset detector for one token, in ``[0, 1]``."""
    if token.onset_distance_s is None:
        return 0.3
    return math.exp(-max(0.0, token.onset_distance_s - 0.01) / 0.05)


def score_tokens(
    lines: Sequence[Sequence[RefinedToken]], windows: Sequence[LineWindow]
) -> list[list[float]]:
    """Compute the confidence of every token.

    Args:
        lines: Refined token timings per line.
        windows: Coarse window of each line (with per-token hints).

    Returns:
        Confidence values with the same shape as ``lines``.
    """
    result: list[list[float]] = []
    for line, window in zip(lines, windows, strict=True):
        values: list[float] = []
        for index, token in enumerate(line):
            if token.locked:
                values.append(1.0)
                continue
            if token.estimated:
                values.append(_ESTIMATED_CONFIDENCE)
                continue
            hint = window.token_hints[index] if index < len(window.token_hints) else None
            combined = (
                WEIGHT_ALIGNER * min(1.0, max(0.0, token.score))
                + WEIGHT_COARSE * coarse_agreement(token, hint, window)
                + WEIGHT_ONSET * onset_agreement(token)
            )
            values.append(round(min(1.0, max(0.0, combined)), 3))
        result.append(values)
    return result
