from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from karaforge.align.coarse import LineWindow, LyricLine
from karaforge.align.engine import AlignmentOutput, lyric_lines, run_alignment
from karaforge.align.features import VocalFeatures
from karaforge.align.fine import TokenTiming, fine_align
from karaforge.audio.io import MODEL_RATE, FloatArray
from karaforge.errors import AlignmentError, JobCancelledError
from karaforge.pipeline.profiles import AlignSettings
from karaforge.project import Line, Project, Token
from karaforge.runtime import CancelToken, null_progress
from karaforge.stages.align import alignment_fingerprint, apply_alignment
from karaforge.text.tokenize import TokenKind
from support import FakeAligner, lyric_line, make_features, sung_words


def silence(seconds: float) -> FloatArray:
    return np.zeros(round(seconds * MODEL_RATE), dtype=np.float32)


def window(start: float, end: float, size: int) -> LineWindow:
    return LineWindow(start, end, 1.0, "asr", [None] * size)


def run_fine(
    lines: list[LyricLine],
    windows: list[LineWindow],
    aligner: FakeAligner,
    *,
    pad_s: float = 1.0,
    max_window_s: float | None = None,
    features: VocalFeatures | None = None,
    anchor_context: bool = True,
) -> list[list[TokenTiming]]:
    return fine_align(
        lines,
        windows,
        silence(60.0),
        aligner,
        language="zh-TW",
        pad_s=pad_s,
        progress=null_progress,
        cancel=CancelToken(),
        max_window_s=max_window_s,
        features=features,
        anchor_context=anchor_context,
    )


def test_each_line_is_aligned_in_its_padded_window() -> None:
    aligner = FakeAligner()
    lines = [lyric_line("L1", "一二三四"), lyric_line("L2", "五六")]
    result = run_fine(lines, [window(10.0, 14.0, 4), window(20.0, 22.0, 2)], aligner)
    assert [request.audio.size / MODEL_RATE for request in aligner.requests] == [6.0, 4.0]
    assert [token.start_s for token in result[0]] == pytest.approx([9.0, 10.5, 12.0, 13.5])
    assert [token.start_s for token in result[1]] == pytest.approx([19.0, 21.0])
    assert all(token.score == 0.8 and not token.locked for line in result for token in line)
    assert [unit.text for unit in aligner.requests[0].units] == ["一", "二", "三", "四"]
    assert aligner.requests[0].units[0].reading == "yi"
    # Nothing else is sung near either window, so neither is "open".
    assert not any(request.open_start or request.open_end for request in aligner.requests)


def test_window_is_clamped_to_the_audio() -> None:
    aligner = FakeAligner()
    run_fine([lyric_line("L1", "一二")], [window(0.2, 59.9, 2)], aligner)
    assert aligner.requests[0].audio.size == 60 * MODEL_RATE


def test_tokens_next_to_a_lock_are_aligned_together_with_it() -> None:
    aligner = FakeAligner()
    line = lyric_line("L1", "一二三四五六", locked={2: (12.0, 12.4), 5: (15.0, 15.8)})
    result = run_fine([line], [window(10.0, 16.0, 6)], aligner)[0]
    # The locked tokens are exactly where the user put them.
    assert [(token.start_s, token.end_s, token.locked) for token in (result[2], result[5])] == [
        (12.0, 12.4, True),
        (15.0, 15.8, True),
    ]
    first, second = aligner.requests
    # Run 1 (tokens 0-1): from the window start (10 - 1 s pad) to the end of the lock that
    # follows, and the locked token is part of the text.
    assert [unit.text for unit in first.units] == ["一", "二", "三"]
    assert first.offset_s == pytest.approx(9.0)
    assert first.audio.size / MODEL_RATE == pytest.approx(3.4)
    # Run 2 (tokens 3-4): from the start of the lock before it to the end of the lock after.
    assert [unit.text for unit in second.units] == ["三", "四", "五", "六"]
    assert second.offset_s == pytest.approx(12.0)
    assert second.audio.size / MODEL_RATE == pytest.approx(3.8)
    assert not (second.open_start or second.open_end)
    assert second.prefix_units == () and second.suffix_units == ()
    # Only the run's own timings are used (the fake aligner spaces its units evenly) ...
    assert [token.start_s for token in result[3:5]] == pytest.approx([12.95, 13.9])
    assert all(not token.locked for token in (*result[:2], *result[3:5]))
    # ... and they stay between the starts of the locks around them.
    assert all(9.0 <= token.start_s <= 12.0 for token in result[:2])
    assert all(12.0 < token.start_s <= 15.0 for token in result[3:5])


def test_a_very_short_lock_after_a_run_still_gets_some_audio() -> None:
    aligner = FakeAligner()
    line = lyric_line("L1", "一二三", locked={2: (12.0, 12.05)})
    run_fine([line], [window(10.0, 12.05, 3)], aligner)
    # 0.3 s after the start of the locked token, not just its 50 ms.
    assert aligner.requests[0].audio.size / MODEL_RATE == pytest.approx(3.3)


def test_cutting_at_the_locks_is_still_available_for_comparison() -> None:
    aligner = FakeAligner()
    line = lyric_line("L1", "一二三四五六", locked={2: (12.0, 12.4), 5: (15.0, 15.8)})
    result = run_fine([line], [window(10.0, 16.0, 6)], aligner, anchor_context=False)[0]
    # Run 1: tokens 0-1 from the window start up to the first lock.
    assert [unit.text for unit in aligner.requests[0].units] == ["一", "二"]
    assert aligner.requests[0].audio.size / MODEL_RATE == pytest.approx(3.0)
    # Run 2: tokens 3-4 strictly between the two locks.
    assert aligner.requests[1].audio.size / MODEL_RATE == pytest.approx(2.6)
    assert [token.start_s for token in result[3:5]] == pytest.approx([12.4, 13.7])
    assert not any(request.open_start or request.open_end for request in aligner.requests)


def test_a_window_too_long_for_the_aligner_falls_back_to_cutting() -> None:
    aligner = FakeAligner()
    line = lyric_line("L1", "一二三四", locked={0: (10.0, 10.4), 3: (20.0, 26.0)})
    run_fine([line], [window(10.0, 26.0, 4)], aligner, max_window_s=12.0)
    # With the locks included the audio would be 16 s; between them it is 9.6 s.
    assert [unit.text for unit in aligner.requests[0].units] == ["二", "三"]
    assert aligner.requests[0].audio.size / MODEL_RATE == pytest.approx(9.6)


def test_locks_in_other_lines_bound_the_window() -> None:
    aligner = FakeAligner()
    lines = [
        lyric_line("L1", "一二", locked={1: (11.0, 11.5)}),
        lyric_line("L2", "三四"),
        lyric_line("L3", "五六", locked={0: (13.2, 13.6)}),
    ]
    result = run_fine(lines, [window(10, 11.5, 2), window(12, 13, 2), window(13.2, 14, 2)], aligner)
    middle = result[1]
    assert middle[0].start_s >= 11.5
    assert middle[-1].end_s <= 13.2
    assert aligner.requests[1].audio.size / MODEL_RATE == pytest.approx(1.7)


def test_run_without_room_is_spread_evenly_and_flagged() -> None:
    aligner = FakeAligner()
    # Two tokens would have to start within 50 ms: between the *starts* of the two locks.
    line = lyric_line("L1", "一二三四", locked={0: (10.0, 10.5), 3: (10.05, 11.0)})
    result = run_fine([line], [window(10.0, 11.0, 4)], aligner)[0]
    assert aligner.requests == []
    assert [token.estimated for token in result] == [False, True, True, False]
    assert [token.start_s for token in result[1:3]] == pytest.approx([10.03, 10.04])
    assert all(token.score == 0.0 for token in result[1:3])


def test_a_lock_that_ends_late_does_not_push_its_neighbours() -> None:
    aligner = FakeAligner()
    # The first lock is said to last until 10.5 s although the next token is sung earlier:
    # where a token starts is what the user marked, its end is only a by-product.
    line = lyric_line("L1", "一二三四", locked={0: (10.0, 10.5), 3: (10.52, 11.0)})
    result = run_fine([line], [window(10.0, 11.0, 4)], aligner)[0]
    assert [unit.text for unit in aligner.requests[0].units] == ["一", "二", "三", "四"]
    assert not any(token.estimated for token in result)
    assert 10.0 < result[1].start_s < 10.5


def test_punctuation_only_tokens_are_not_sent_to_the_aligner() -> None:
    aligner = FakeAligner()
    line = lyric_line("L1", "……")
    assert line.kinds == (TokenKind.NONE,)
    result = run_fine([line], [window(5.0, 6.0, 1)], aligner)[0]
    assert aligner.requests == []
    assert result[0].estimated


def test_neighbouring_lines_are_offered_as_context_when_windows_touch() -> None:
    aligner = FakeAligner()
    lines = [lyric_line("L1", "一二三四五六"), lyric_line("L2", "七八"), lyric_line("L3", "九十")]
    run_fine(lines, [window(10, 12, 6), window(12.5, 13.5, 2), window(30, 31, 2)], aligner)
    first, second, third = aligner.requests
    assert [unit.text for unit in first.prefix_units] == []
    assert [unit.text for unit in first.suffix_units] == ["七", "八"]
    assert [unit.text for unit in second.prefix_units] == ["三", "四", "五", "六"]
    assert [unit.text for unit in second.suffix_units] == []
    assert list(third.prefix_units) == []
    # "Open" means: a neighbour may be audible at that end of the window.
    assert [(r.open_start, r.open_end) for r in aligner.requests] == [
        (False, True),
        (True, False),
        (False, False),
    ]


def test_context_can_be_switched_off_but_the_window_stays_open() -> None:
    aligner = FakeAligner()
    lines = [lyric_line("L1", "一二三四五六"), lyric_line("L2", "七八")]
    fine_align(
        lines,
        [window(10, 12, 6), window(12.5, 13.5, 2)],
        silence(60.0),
        aligner,
        language="zh-TW",
        pad_s=1.0,
        progress=null_progress,
        cancel=CancelToken(),
        context_tokens=0,
    )
    first, second = aligner.requests
    assert list(first.suffix_units) == [] and list(second.prefix_units) == []
    assert first.open_end and second.open_start


def test_singing_at_the_window_edge_also_triggers_context() -> None:
    aligner = FakeAligner()
    lines = [lyric_line("L1", "一二"), lyric_line("L2", "三四")]
    # Coarse windows are far apart, but the voice is active where line 2's padded window starts.
    features = make_features(60.0, [(5.0, 19.5)])
    run_fine(lines, [window(5, 6, 2), window(20, 21, 2)], aligner, features=features)
    assert [unit.text for unit in aligner.requests[1].prefix_units] == ["一", "二"]
    assert aligner.requests[1].open_start is True


def test_window_longer_than_the_aligner_limit_is_shortened() -> None:
    aligner = FakeAligner()
    run_fine([lyric_line("L1", "一二")], [window(10.0, 50.0, 2)], aligner, max_window_s=20.0)
    assert aligner.requests[0].audio.size / MODEL_RATE == pytest.approx(20.0)


def test_cancellation_is_honoured_between_lines() -> None:
    token = CancelToken()
    token.cancel()
    with pytest.raises(JobCancelledError):
        fine_align(
            [lyric_line("L1", "一二")],
            [window(1.0, 2.0, 2)],
            silence(5.0),
            FakeAligner(),
            language="zh",
            pad_s=1.0,
            progress=null_progress,
            cancel=token,
        )


# ---------------------------------------------------------------------------- run_alignment


def test_run_alignment_end_to_end_with_transcript_and_refinement() -> None:
    lines = [lyric_line("L1", "夜空裡的星星"), lyric_line("L2", "慢慢亮起來")]
    words = [*sung_words("夜空裡的星星", 10.0, 0.5), *sung_words("慢慢亮起來", 20.0, 0.5)]
    features = make_features(40.0, [(10.0, 13.2), (20.0, 23.0)], onsets=[10.0, 20.0])
    aligner = FakeAligner()
    output = run_alignment(
        lines,
        audio=silence(40.0),
        features=features,
        words=words,
        aligner=aligner,
        settings=AlignSettings(),
        language="zh-TW",
    )
    assert [window.source for window in output.windows] == ["asr", "asr"]
    # The fake aligner starts each line at the padded window start (in silence); refinement
    # moves the first token to where the voice comes in.
    assert output.tokens[0][0].start_s == pytest.approx(10.0, abs=0.011)
    assert output.tokens[1][0].start_s == pytest.approx(20.0, abs=0.011)
    # The last token starts 33 ms before the voice stops: it gets the minimum length only.
    assert output.tokens[0][-1].end_s == pytest.approx(13.2, abs=0.05)
    flat = [token.start_s for line in output.tokens for token in line]
    assert flat == sorted(flat)
    assert set(output.seconds) == {"coarse", "fine", "refine"}
    assert all(0.0 <= value <= 1.0 for line in output.confidences for value in line)


def test_coarse_modes() -> None:
    lines = [lyric_line("L1", "一二三"), lyric_line("L2", "四五六")]
    words = [*sung_words("一二三", 10.0), *sung_words("四五六", 20.0)]
    features = make_features(40.0, [(11.0, 12.5), (21.0, 22.5)])

    def run(aligner: FakeAligner, settings: AlignSettings) -> AlignmentOutput:
        return run_alignment(
            lines,
            audio=silence(40.0),
            features=features,
            words=words,
            aligner=aligner,
            settings=settings,
            language="zh",
        )

    with_asr = run(FakeAligner(), AlignSettings())
    assert [window.source for window in with_asr.windows] == ["asr", "asr"]

    regions = run(FakeAligner(), AlignSettings(coarse="regions"))
    assert [window.source for window in regions.windows] == ["regions", "regions"]
    assert regions.windows[0].start_s == pytest.approx(11.0)

    aligner = FakeAligner()
    whole = run(aligner, AlignSettings(coarse="global"))
    assert len(aligner.requests) == 1
    assert len(aligner.requests[0].units) == 6
    assert aligner.requests[0].audio.size == 40 * MODEL_RATE
    assert [len(line) for line in whole.tokens] == [3, 3]


def test_run_alignment_rejects_empty_input() -> None:
    features = make_features(1.0, [])
    with pytest.raises(AlignmentError):
        run_alignment(
            [],
            audio=silence(1.0),
            features=features,
            words=[],
            aligner=FakeAligner(),
            settings=AlignSettings(),
            language="zh",
        )
    with pytest.raises(AlignmentError):
        run_alignment(
            [lyric_line("L1", "一")],
            audio=silence(0.0),
            features=features,
            words=[],
            aligner=FakeAligner(),
            settings=AlignSettings(),
            language="zh",
        )


# ------------------------------------------------------------------- project <-> alignment


def project_with(*lines: Line) -> Project:
    return Project(lines=list(lines))


def test_lyric_lines_carry_readings_locks_and_skip_empty_lines() -> None:
    project = project_with(
        Line(
            id="L001",
            tokens=[
                Token(text="重", ruby="ㄓㄨㄥˋ", ruby_source="manual"),
                Token(text="複,", ruby="ㄈㄨˋ", ruby_source="auto"),
                Token(text="go! ", start_ms=1500, end_ms=1900, locked=True, source="manual"),
                Token(text="……"),
            ],
        ),
        Line(id="L002"),
    )
    lines = lyric_lines(project)
    assert [line.id for line in lines] == ["L001"]
    line = lines[0]
    assert line.cores == ("重", "複", "go", "")
    assert line.kinds == (TokenKind.HAN, TokenKind.HAN, TokenKind.WORD, TokenKind.NONE)
    # The manual reading wins; the automatic ruby of 複 is ignored in favour of context.
    assert line.readings == ("zhong", "fu", "go", "")
    assert line.locked == (None, None, (1.5, 1.9), None)


def alignment_for(project: Project, shift_ms: int = 1000) -> dict[str, Any]:
    return {
        "lines": [
            {
                "id": line.id,
                "tokens": [
                    {
                        "text": token.text,
                        "start_ms": shift_ms + 500 * index,
                        "end_ms": shift_ms + 500 * index + 400,
                        "confidence": 0.7,
                    }
                    for index, token in enumerate(line.tokens)
                ],
            }
            for line in project.lines
        ]
    }


def test_apply_alignment_never_touches_locked_tokens() -> None:
    project = project_with(
        Line(
            id="L001",
            tokens=[
                Token(text="一"),
                Token(text="二", start_ms=4000, end_ms=4300, locked=True, source="manual"),
                Token(text="三", start_ms=9000, end_ms=9100, confidence=0.2),
            ],
        )
    )
    updated = apply_alignment(project, alignment_for(project))
    assert updated == 2
    first, locked, third = project.lines[0].tokens
    assert (first.start_ms, first.end_ms, first.confidence, first.source) == (
        1000,
        1400,
        0.7,
        "auto",
    )
    assert locked == Token(text="二", start_ms=4000, end_ms=4300, locked=True, source="manual")
    assert (third.start_ms, third.end_ms, third.confidence) == (2000, 2400, 0.7)


def test_apply_alignment_skips_lines_edited_since_they_were_aligned() -> None:
    project = project_with(
        Line(id="L001", tokens=[Token(text="一"), Token(text="二")]),
        Line(id="L002", tokens=[Token(text="三")]),
    )
    alignment = alignment_for(project)
    project.lines[0].tokens[1] = Token(text="兩")  # text changed after alignment started
    assert apply_alignment(project, alignment) == 1
    assert not project.lines[0].tokens[0].is_timed
    assert project.lines[1].tokens[0].start_ms == 1000


def test_apply_alignment_can_be_limited_to_some_lines() -> None:
    project = project_with(
        Line(id="L001", tokens=[Token(text="一")]),
        Line(id="L002", tokens=[Token(text="二")]),
    )
    assert apply_alignment(project, alignment_for(project), only_lines=["L002"]) == 1
    assert not project.lines[0].tokens[0].is_timed
    assert project.lines[1].tokens[0].is_timed


def test_fingerprint_ignores_unlocked_times_but_not_text_or_locks() -> None:
    def build(**token: object) -> Project:
        return project_with(Line(id="L001", tokens=[Token.model_validate({"text": "一", **token})]))

    base = alignment_fingerprint(build(), None)
    assert alignment_fingerprint(build(start_ms=100, end_ms=200, confidence=0.5), None) == base
    assert alignment_fingerprint(build(start_ms=100, end_ms=200, locked=True), None) != base
    assert alignment_fingerprint(build(ruby="ㄧ", ruby_source="manual"), None) != base
    assert alignment_fingerprint(build(ruby="ㄧ", ruby_source="auto"), None) == base
    assert alignment_fingerprint(build(), ["L001"]) != base
    other_text = project_with(Line(id="L001", tokens=[Token(text="二")]))
    assert alignment_fingerprint(other_text, None) != base


def test_identical_requests_are_answered_from_memory() -> None:
    aligner = FakeAligner()
    lines = [lyric_line("L1", "一二三四"), lyric_line("L2", "五六")]
    windows = [window(10.0, 14.0, 4), window(20.0, 22.0, 2)]
    first = run_fine(lines, windows, aligner)
    assert len(aligner.requests) == 2
    second = run_fine(lines, windows, aligner)
    assert len(aligner.requests) == 2  # nothing was asked again
    assert [[t.start_s for t in line] for line in second] == [
        [t.start_s for t in line] for line in first
    ]
    # Locking a token changes the runs of its line only: line 2 is still remembered.
    locked = [lyric_line("L1", "一二三四", locked={1: (11.0, 11.3)}), lines[1]]
    run_fine(locked, windows, aligner)
    assert len(aligner.requests) == 4  # two new runs around the lock in line 1
    # Another aligner (or another audio) never reuses these answers.
    other = FakeAligner()
    run_fine(lines, windows, other)
    assert len(other.requests) == 2
