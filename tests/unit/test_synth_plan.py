"""Tests of the synthetic song generator that need no TTS: planning, vocoder maths, band."""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from karaforge.io.importers.lyrics_txt import parse_lyrics_text
from kfbench.synth.accompaniment import PROGRESSIONS, Arrangement, Section, render_accompaniment
from kfbench.synth.corpus import CORPUS
from kfbench.synth.dataset import LANGUAGES, SPLITS, song_entry, split_entries
from kfbench.synth.song import (
    MAX_DURATION_S,
    MIN_DURATION_S,
    count_syllables,
    lyrics_text,
    plan_song,
)
from kfbench.synth.vocal import (
    NoteSpec,
    active_bounds,
    apply_fades,
    hz_to_midi,
    midi_to_hz,
    normalise_rms,
    render_note,
    rms_envelope,
    trim_to_active,
    upsample,
)

ALL_SONGS = [
    (language, seed) for language in LANGUAGES for seed in (*SPLITS["test"], *SPLITS["dev"])
]


BENCH_ONLY = "needs the benchmark tools (uv sync --extra cpu --group bench): the WORLD vocoder"


def test_splits_are_disjoint_and_large_enough() -> None:
    assert len(SPLITS["test"]) == 10
    assert not set(SPLITS["test"]) & set(SPLITS["dev"])
    assert len(split_entries("test")) == 30
    assert song_entry("zh", 1003).song_id == "zh-1003"
    assert song_entry("zh", 1003).mix(5).name == "mix_snr05.wav"


def test_corpus_lines_are_distinct_and_tokenizable() -> None:
    for language, lines in CORPUS.items():
        assert len(lines) >= 40, language
        assert len(set(lines)) == len(lines), language
        parsed = parse_lyrics_text("\n".join(lines))
        assert len(parsed.lines) == len(lines)
    assert all(not line.isascii() for line in CORPUS["zh"])
    assert all(line.isascii() for line in CORPUS["en"])
    assert all(
        not line.isascii() and any(c.isascii() and c.isalpha() for c in line)
        for line in CORPUS["mixed"]
    )


def test_planning_is_deterministic() -> None:
    assert plan_song("zh", 1000) == plan_song("zh", 1000)
    assert plan_song("zh", 1000) != plan_song("zh", 1001)
    assert plan_song("zh", 1000).lines != plan_song("mixed", 1000).lines


@pytest.mark.parametrize(("language", "seed"), ALL_SONGS)
def test_every_planned_song_meets_the_specification(language: str, seed: int) -> None:
    plan = plan_song(language, seed)
    arrangement = plan.arrangement
    assert MIN_DURATION_S <= arrangement.duration_s <= MAX_DURATION_S
    kinds = [section.kind for section in arrangement.sections]
    assert kinds == ["intro", "verse", "chorus", "interlude", "verse", "chorus", "outro"]
    interlude = arrangement.sections[3]
    assert interlude.bars * arrangement.bar_s > 8.0
    assert arrangement.sections[0].bars * arrangement.bar_s >= 4.5

    tokens = [token for line in plan.lines for token in line.tokens]
    assert len(plan.lines) >= 4 and len(tokens) >= 20
    starts = [token.start_s for token in tokens]
    assert starts == sorted(starts)
    assert all(later - earlier >= 0.119 for earlier, later in pairwise(starts))
    assert all(token.sound_s >= 0.12 for token in tokens)
    assert tokens[-1].start_s + tokens[-1].sound_s < arrangement.duration_s

    # The gap across the interlude is the long pause the specification asks for.
    gaps = [
        later.tokens[0].start_s - (earlier.tokens[-1].start_s + earlier.tokens[-1].sound_s)
        for earlier, later in pairwise(plan.lines)
    ]
    assert max(gaps) > 8.0
    # A legato token is held into the next one; the others end before it.
    for line in plan.lines:
        for token, following in pairwise(line.tokens):
            overlap = token.start_s + token.sound_s - following.start_s
            assert (overlap > 0.0) == token.legato
        assert not line.tokens[-1].legato


def test_chorus_is_repeated_and_duets_use_three_singers() -> None:
    plan = plan_song("zh", 1003)  # seeds ending in 3, 6, 9 are duets
    singers = {line.singer for line in plan.lines}
    assert singers == {"m", "f", "all"}
    solo = plan_song("zh", 1000)
    assert len({line.singer for line in solo.lines}) == 1
    texts = [line.text for line in solo.lines]
    assert len(set(texts)) < len(texts)  # the chorus text occurs twice
    assert set(plan.voices) == {"f", "m"}


def test_dataset_covers_fast_passages_long_notes_and_pauses() -> None:
    for language in LANGUAGES:
        tokens = [
            token
            for seed in SPLITS["test"]
            for line in plan_song(language, seed).lines
            for token in line.tokens
        ]
        durations = np.array([token.sound_s for token in tokens])
        assert (durations < 0.25).mean() > 0.03, language  # fast passages
        assert (durations > 1.0).mean() > 0.03, language  # long notes
        assert np.mean([token.vibrato for token in tokens]) > 0.05, language
        assert 0.15 < np.mean([token.legato for token in tokens]) < 0.75, language
        pauses = 0
        for seed in SPLITS["test"]:
            for line in plan_song(language, seed).lines:
                for token, following in pairwise(line.tokens):
                    pauses += following.start_s - (token.start_s + token.sound_s) > 0.3
        assert pauses >= 5, language


def test_lyrics_file_matches_the_plan() -> None:
    plan = plan_song("mixed", 1003)
    parsed = parse_lyrics_text(lyrics_text(plan))
    assert [line.text for line in parsed.lines] == [line.text for line in plan.lines]
    assert [line.singer for line in parsed.lines] == [line.singer for line in plan.lines]
    assert [line.paragraph for line in parsed.lines] == [line.paragraph for line in plan.lines]
    for parsed_line, planned in zip(parsed.lines, plan.lines, strict=True):
        assert [token.text for token in parsed_line.tokens] == [
            token.text for token in planned.tokens
        ]
    assert parsed.meta["title"] == plan.title


def test_count_syllables() -> None:
    assert [
        count_syllables(word) for word in ("a", "sky", "love", "tonight", "remember", "little")
    ] == [
        1,
        1,
        1,
        2,
        3,
        2,
    ]
    assert count_syllables("...") == 1


# ------------------------------------------------------------------------------ vocoder


def voiced_clip(seconds: float = 0.4, rate: int = 24000, pitch: float = 200.0) -> np.ndarray:
    """A harmonic tone with a short attack: enough of a "voice" for the vocoder."""
    time = np.arange(round(seconds * rate)) / rate
    tone = sum(np.sin(2 * np.pi * pitch * k * time) / k for k in range(1, 8))
    envelope = np.clip(time / 0.02, 0, 1) * np.clip((seconds - time) / 0.04, 0, 1)
    return (0.2 * tone * envelope).astype(np.float32)


def test_active_bounds_and_trimming() -> None:
    rate = 24000
    clip = np.concatenate([np.zeros(2400, np.float32), voiced_clip(), np.zeros(4800, np.float32)])
    bounds = active_bounds(clip, rate)
    assert bounds is not None
    assert bounds[0] == pytest.approx(2400, abs=200)
    assert bounds[1] == pytest.approx(2400 + 9600, abs=400)
    trimmed = trim_to_active(clip, rate)
    assert trimmed.size < clip.size - 6000
    assert active_bounds(np.zeros(1000, np.float32), rate) is None
    assert active_bounds(np.zeros(0, np.float32), rate) is None
    assert rms_envelope(clip, rate).shape == clip.shape


def test_note_rendering_sets_pitch_and_duration() -> None:
    pytest.importorskip("pyworld", reason=BENCH_ONLY)
    rate = 24000
    clip = voiced_clip(0.4, rate, pitch=200.0)
    for midi, duration in ((57.0, 0.25), (62.0, 0.9), (50.0, 1.6)):
        audio = render_note(clip, rate, NoteSpec(midi=midi, duration_s=duration))
        assert audio.size == pytest.approx(duration * rate, abs=rate * 0.02)
        spectrum = np.abs(np.fft.rfft(audio * np.hanning(audio.size)))
        peak_hz = np.fft.rfftfreq(audio.size, 1 / rate)[int(np.argmax(spectrum[: audio.size // 8]))]
        harmonic = peak_hz / midi_to_hz(midi)
        assert abs(harmonic - round(harmonic)) < 0.06  # energy sits on a harmonic of the note
        bounds = active_bounds(audio, rate)
        assert bounds is not None and bounds[0] < 0.04 * rate
        assert float(np.abs(audio).max()) <= 0.95 + 1e-6


def test_vibrato_modulates_the_pitch_of_long_notes() -> None:
    pytest.importorskip("pyworld", reason=BENCH_ONLY)
    rate = 24000
    clip = voiced_clip(0.4, rate)
    plain = render_note(clip, rate, NoteSpec(midi=57.0, duration_s=1.2))
    wobbly = render_note(clip, rate, NoteSpec(midi=57.0, duration_s=1.2, vibrato_cents=45.0))
    assert plain.shape == wobbly.shape
    assert float(np.abs(plain - wobbly).mean()) > 1e-3


def test_too_short_clip_gives_silence_of_the_requested_length() -> None:
    audio = render_note(np.zeros(10, np.float32), 24000, NoteSpec(midi=60.0, duration_s=0.5))
    assert audio.size == 12000 and not audio.any()


def test_signal_helpers() -> None:
    assert midi_to_hz(69.0) == pytest.approx(440.0)
    assert hz_to_midi(880.0) == pytest.approx(81.0)
    faded = apply_fades(np.ones(2400, np.float32), 24000)
    assert faded[0] == 0.0 and faded[-1] == 0.0 and faded[1200] == 1.0
    loud = normalise_rms(voiced_clip() * 3, 0.1)
    sounding = loud[np.abs(loud) >= 0.1 * np.abs(loud).max()]
    assert float(np.sqrt(np.mean(sounding.astype(np.float64) ** 2))) == pytest.approx(0.1, rel=0.05)
    assert normalise_rms(np.zeros(100, np.float32)).sum() == 0
    doubled = upsample(voiced_clip(0.1), 24000, 48000)
    assert doubled.size == 2 * 2400
    assert upsample(doubled, 48000, 48000) is doubled


# --------------------------------------------------------------------------------- band


def test_accompaniment_is_stereo_bounded_and_rhythmic() -> None:
    arrangement = Arrangement(
        bpm=120.0,
        key=0,
        progression=0,
        sections=(Section("intro", 0, 1), Section("verse", 1, 2), Section("chorus", 3, 1)),
    )
    assert arrangement.beat_s == 0.5 and arrangement.bar_s == 2.0
    assert arrangement.total_bars == 4 and arrangement.duration_s == 8.0
    assert arrangement.section_at(2).kind == "verse" and arrangement.section_at(99).kind == "chorus"
    assert arrangement.chord(5) == PROGRESSIONS[0][1]
    assert arrangement.chord_pitch_classes(0) == (0, 4, 7)

    rate = 16000
    band = render_accompaniment(arrangement, rate, np.random.default_rng(1))
    assert band.shape == (round(8.0 * rate) + rate // 2, 2)
    assert float(np.abs(band).max()) == pytest.approx(0.9, abs=1e-3)
    assert not np.allclose(band[:, 0], band[:, 1])
    again = render_accompaniment(arrangement, rate, np.random.default_rng(1))
    assert np.array_equal(band, again)
    # Kicks land on beats 1 and 3 of the verse: the low band is louder there than between.
    mono = band.mean(axis=1)
    on_beat = float(np.abs(mono[round(2.0 * rate) : round(2.05 * rate)]).mean())
    off_beat = float(np.abs(mono[round(2.3 * rate) : round(2.35 * rate)]).mean())
    assert on_beat > 1.5 * off_beat
