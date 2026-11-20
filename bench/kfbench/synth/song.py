"""Plan and render one synthetic benchmark song with exact ground-truth timing.

A song is planned from nothing but ``(language, seed)``: tempo, key, structure, which corpus
lines are sung, the rhythm and melody of every token.  Rendering then synthesises each token
on its own, sings it with the vocoder, and drops it into the vocal track at its planned sample
position.  Because every token is placed individually, its true start and end are known from
construction; they are measured on the rendered clip with the same loudness threshold that
defines "sounding" everywhere in the generator (see :data:`kfbench.synth.vocal.ACTIVE_THRESHOLD`).

Realism features required by the specification: long notes (the vowel is sustained, not the
whole clip stretched), pitch glides and vibrato, fast passages, pauses inside lines, an
instrumental interlude longer than eight seconds, repeated choruses, duets, and mixing with a
synthetic band at several signal-to-noise ratios.

Two things are done specifically so that the benchmark is not easier than real singing:

* *Legato.*  In half of the lines each note keeps sounding until the next one has started
  (the clips overlap and cross-fade), so there is no dip to silence that would give every
  token a trivially detectable onset.
* *Singing pitch.*  Melodies sit a fourth above the voice's speaking pitch, as sung melodies
  do, instead of at the pitch the TTS voice was trained to speak at.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt
import soundfile as sf
from scipy.signal import fftconvolve

from karaforge.text.tokenize import TextToken, TokenKind, tokenize
from kfbench.synth.accompaniment import PROGRESSIONS, Arrangement, Section, render_accompaniment
from kfbench.synth.corpus import CORPUS
from kfbench.synth.tts import ClipCache, TTSLanguage
from kfbench.synth.vocal import (
    NoteSpec,
    active_bounds,
    hz_to_midi,
    median_f0,
    render_note,
    trim_to_active,
    upsample,
)

GENERATOR_VERSION = "1"
"""Bump when a change alters the generated audio or ground truth."""

OUTPUT_RATE = 48000
SNR_LEVELS_DB: tuple[int, ...] = (0, 5, 10, 20)
MIN_DURATION_S = 30.0
MAX_DURATION_S = 90.0
_MIN_SOUND_S = 0.12
_LEGATO_OVERLAP_S = 0.045
_SINGING_OFFSET_SEMITONES = 5.0
_PENTATONIC = (0, 2, 4, 7, 9)
_LANGUAGE_INDEX = {"zh": 1, "en": 2, "mixed": 3}
_SALT = 20261119

FloatArray = npt.NDArray[np.float32]
SingerId = Literal["m", "f", "all"]

VOICES: dict[str, dict[str, tuple[str, ...]]] = {
    "zh": {"f": ("zf_xiaobei", "zf_xiaoyi"), "m": ("zm_yunxi", "zm_yunjian")},
    "en": {"f": ("af_heart", "af_bella"), "m": ("am_michael", "am_fenrir")},
    "mixed": {"f": ("zf_xiaobei", "zf_xiaoyi"), "m": ("zm_yunxi", "zm_yunjian")},
}
_SINGER_TAGS = {"m": "男", "f": "女", "all": "合"}


@dataclass
class PlannedToken:
    """One token with its planned rhythm and melody."""

    text: str
    core: str
    language: TTSLanguage
    start_s: float
    sound_s: float
    step: int
    """Position on the pentatonic ladder relative to the singer's comfortable centre."""
    glide_cents: float
    detune_cents: float
    vibrato: bool
    legato: bool
    """The note is held into the start of the next one (no gap, cross-faded)."""


@dataclass
class PlannedLine:
    """One lyric line."""

    text: str
    singer: SingerId
    paragraph: int
    tokens: list[PlannedToken]


@dataclass
class SongPlan:
    """A fully specified song, independent of any audio."""

    song_id: str
    language: str
    seed: int
    title: str
    arrangement: Arrangement
    voices: dict[str, str]
    lines: list[PlannedLine]


@dataclass
class _LineDraft:
    """Rhythm of a line relative to the bar it starts in."""

    text: str
    tokens: list[TextToken]
    offsets_beats: list[float]
    sound_beats: list[float]
    steps: list[int]
    glides: list[float]
    detunes: list[float]
    vibratos: list[bool]
    legatos: list[bool]
    bars: int


@dataclass
class TruthToken:
    """Ground truth for one token."""

    text: str
    start_ms: int
    end_ms: int
    midi: int


@dataclass
class TruthLine:
    """Ground truth for one line."""

    singer: str
    paragraph: int
    text: str
    tokens: list[TruthToken] = field(default_factory=list[TruthToken])


def count_syllables(word: str) -> int:
    """Rough English syllable count (vowel groups, silent final ``e``)."""
    lowered = re.sub(r"[^a-z]", "", word.lower())
    if not lowered:
        return 1
    groups = re.findall(r"[aeiouy]+", lowered)
    count = len(groups)
    if lowered.endswith("e") and not lowered.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def _token_language(token: TextToken) -> TTSLanguage:
    return "en" if token.kind is TokenKind.WORD else "zh"


def _draft_line(text: str, beat_s: float, rng: np.random.Generator) -> _LineDraft:
    """Decide the rhythm and melody of one line."""
    tokens = [token for token in tokenize(text) if token.core]
    style = str(rng.choice(["normal", "fast", "slow"], p=[0.6, 0.2, 0.2]))
    fast_unit = 0.25 if beat_s * 0.25 >= 0.14 else 0.5
    articulation = float(rng.choice([1.0, 0.9, 0.7], p=[0.5, 0.35, 0.15]))

    position = float(rng.choice([0.0, 0.0, 0.5, 1.0]))
    offsets: list[float] = []
    sounds: list[float] = []
    steps: list[int] = []
    legatos: list[bool] = []
    step = int(rng.integers(-1, 2))
    last = len(tokens) - 1

    for index, token in enumerate(tokens):
        syllables = count_syllables(token.core) if token.kind is TokenKind.WORD else 1
        if style == "fast":
            unit = fast_unit
        elif style == "slow":
            unit = float(rng.choice([1.0, 0.5], p=[0.7, 0.3]))
        else:
            unit = float(rng.choice([0.5, 1.0], p=[0.7, 0.3]))
        grid = min(2.0, unit * syllables)
        if index == last:
            grid += float(rng.choice([0.5, 1.0, 1.5, 2.0, 3.0], p=[0.2, 0.3, 0.25, 0.15, 0.1]))
            sounding = grid * 0.95
        else:
            sounding = grid * articulation
        offsets.append(position)
        sounds.append(sounding)
        steps.append(step)
        position += grid

        # A breath inside the line, at a phrase boundary.
        breath = False
        if index != last and token.text != token.core:
            chance = 0.12 if token.kind is TokenKind.WORD else 0.6
            if rng.random() < chance:
                position += float(rng.choice([0.5, 1.0]))
                breath = True
        legatos.append(articulation == 1.0 and index != last and not breath)
        step = int(np.clip(step + int(rng.choice([-2, -1, -1, 0, 1, 1, 2])), -3, 4))

    bars = max(1, math.ceil((position + 1.0) / 4.0))
    glides = [float(rng.choice([-80.0, -50.0, 0.0, 40.0])) for _ in tokens]
    detunes = [float(rng.uniform(-12.0, 12.0)) for _ in tokens]
    vibratos = [sound * beat_s >= 0.6 and bool(rng.random() < 0.8) for sound in sounds]
    return _LineDraft(
        text, tokens, offsets, sounds, steps, glides, detunes, vibratos, legatos, bars
    )


def plan_song(language: str, seed: int) -> SongPlan:
    """Plan a song deterministically from its language and seed.

    Args:
        language: ``zh``, ``en`` or ``mixed``.
        seed: Any non-negative integer; the same pair always yields the same plan.
    """
    corpus = CORPUS[language]
    rng = np.random.default_rng([_SALT, _LANGUAGE_INDEX[language], seed])
    bpm = float(rng.integers(72, 129))
    beat_s = 60.0 / bpm
    bar_s = 4.0 * beat_s
    key = int(rng.integers(0, 12))
    progression = int(rng.integers(0, len(PROGRESSIONS)))
    target_s = float(rng.uniform(50.0, 88.0))
    duet = seed % 10 in (3, 6, 9)
    lead: SingerId = "f" if int(rng.integers(0, 2)) == 0 else "m"
    voice_pool = VOICES[language]
    voices = {
        "f": voice_pool["f"][int(rng.integers(0, len(voice_pool["f"])))],
        "m": voice_pool["m"][int(rng.integers(0, len(voice_pool["m"])))],
    }

    order = [int(i) for i in rng.permutation(len(corpus))]
    drafts = [_draft_line(corpus[i], beat_s, rng) for i in order[:16]]

    intro_bars = max(2, math.ceil(4.5 / bar_s))
    interlude_bars = math.ceil(8.5 / bar_s)
    outro_bars = 1
    fixed_s = (intro_bars + interlude_bars + outro_bars) * bar_s

    # Verse 1 / chorus / verse 2 draw from disjoint drafts; the chorus is sung twice.
    best: tuple[float, int, int] | None = None
    for verse_lines in range(1, 6):
        for chorus_lines in range(1, 5):
            if 2 * verse_lines + chorus_lines > len(drafts):
                continue
            verse_1 = drafts[:verse_lines]
            chorus = drafts[verse_lines : verse_lines + chorus_lines]
            verse_2 = drafts[verse_lines + chorus_lines : 2 * verse_lines + chorus_lines]
            bars = sum(d.bars for d in verse_1 + verse_2) + 2 * sum(d.bars for d in chorus)
            total = fixed_s + bars * bar_s
            if not MIN_DURATION_S + 1.0 <= total <= MAX_DURATION_S - 1.0:
                continue
            score = abs(total - target_s)
            if best is None or score < best[0]:
                best = (score, verse_lines, chorus_lines)
    if best is None:
        raise RuntimeError(f"could not fit a song for {language} seed {seed}")
    _score, verse_lines, chorus_lines = best
    verse_1 = drafts[:verse_lines]
    chorus = drafts[verse_lines : verse_lines + chorus_lines]
    verse_2 = drafts[verse_lines + chorus_lines : 2 * verse_lines + chorus_lines]

    other: SingerId = "m" if lead == "f" else "f"
    blocks: list[tuple[str, list[_LineDraft], SingerId]] = [
        ("verse", verse_1, lead),
        ("chorus", chorus, "all" if duet else lead),
        ("interlude", [], lead),
        ("verse", verse_2, other if duet else lead),
        ("chorus", chorus, "all" if duet else lead),
    ]

    sections: list[Section] = [Section("intro", 0, intro_bars)]
    lines: list[PlannedLine] = []
    bar = intro_bars
    paragraph = 0
    for kind, block, singer in blocks:
        if kind == "interlude":
            sections.append(Section("interlude", bar, interlude_bars))
            bar += interlude_bars
            continue
        start_bar = bar
        for draft in block:
            origin = bar * bar_s
            planned = [
                PlannedToken(
                    text=token.text,
                    core=token.core,
                    language=_token_language(token),
                    start_s=origin + offset * beat_s,
                    sound_s=max(_MIN_SOUND_S, sound * beat_s)
                    + (_LEGATO_OVERLAP_S if legato else 0.0),
                    step=step,
                    glide_cents=glide,
                    detune_cents=detune,
                    vibrato=vibrato,
                    legato=legato,
                )
                for token, offset, sound, step, glide, detune, vibrato, legato in zip(
                    draft.tokens,
                    draft.offsets_beats,
                    draft.sound_beats,
                    draft.steps,
                    draft.glides,
                    draft.detunes,
                    draft.vibratos,
                    draft.legatos,
                    strict=True,
                )
            ]
            lines.append(PlannedLine(draft.text, singer, paragraph, planned))
            bar += draft.bars
        sections.append(Section(kind, start_bar, bar - start_bar))
        paragraph += 1
    sections.append(Section("outro", bar, outro_bars))

    arrangement = Arrangement(bpm=bpm, key=key, progression=progression, sections=tuple(sections))
    song_id = f"{language}-{seed:04d}"
    return SongPlan(
        song_id=song_id,
        language=language,
        seed=seed,
        title=f"Synthetic {song_id}",
        arrangement=arrangement,
        voices=voices,
        lines=lines,
    )


# ------------------------------------------------------------------------------ rendering


def _ladder(key: int, centre_midi: float) -> tuple[list[int], int]:
    """Pentatonic notes around ``centre_midi`` and the index of the one closest to it."""
    low, high = math.floor(centre_midi) - 10, math.ceil(centre_midi) + 10
    notes = [note for note in range(low, high + 1) if (note - key) % 12 in _PENTATONIC]
    centre_index = min(range(len(notes)), key=lambda i: abs(notes[i] - centre_midi))
    return notes, centre_index


def _voices_for(singer: SingerId, voices: dict[str, str]) -> list[str]:
    if singer == "all":
        return [voices["f"], voices["m"]]
    return [voices[singer]]


def _voice_centre(plan: SongPlan, voice: str, cache: ClipCache, fallback: float) -> float:
    """Comfortable pitch of a voice: the median f0 of the first clips it sings in this song."""
    pitches: list[float] = []
    for line in plan.lines:
        if voice not in _voices_for(line.singer, plan.voices):
            continue
        for token in line.tokens:
            clip = trim_to_active(cache.get(token.core, token.language, voice), cache.sample_rate)
            pitch = median_f0(clip, cache.sample_rate)
            if pitch is not None:
                pitches.append(hz_to_midi(pitch))
            if len(pitches) >= 12:
                return float(np.median(pitches))
    return float(np.median(pitches)) if pitches else fallback


def _reverb(dry: FloatArray, sample_rate: int, rng: np.random.Generator) -> FloatArray:
    """A mild stereo room: exponentially decaying noise, RT60 0.45 s, 16 dB below the dry signal."""
    length = round(0.6 * sample_rate)
    decay = np.exp(-6.9 * np.arange(length) / (0.45 * sample_rate))
    channels: list[FloatArray] = []
    for _ in range(2):
        impulse = rng.standard_normal(length) * decay
        impulse[: round(0.004 * sample_rate)] = 0.0
        wet = fftconvolve(np.asarray(dry, dtype=np.float64), impulse)[: dry.size]
        channels.append(np.asarray(wet, dtype=np.float32))
    wet_stereo = np.stack(channels, axis=1)
    dry_rms = float(np.sqrt(np.mean(np.asarray(dry, dtype=np.float64) ** 2))) or 1.0
    wet_rms = float(np.sqrt(np.mean(wet_stereo.astype(np.float64) ** 2))) or 1.0
    return (wet_stereo * np.float32(dry_rms / wet_rms * 10.0 ** (-16.0 / 20.0))).astype(np.float32)


@dataclass
class RenderedSong:
    """Paths of the files written for one song."""

    directory: Path
    lyrics: Path
    truth: Path
    vocals: Path
    mixes: dict[int, Path]
    duration_ms: int


def render_song(
    plan: SongPlan,
    cache: ClipCache,
    directory: Path,
    snr_levels: tuple[int, ...] = SNR_LEVELS_DB,
) -> RenderedSong:
    """Render a planned song and write audio, lyrics and ground truth into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    arrangement = plan.arrangement
    clip_rate = cache.sample_rate
    vocal = np.zeros(round(arrangement.duration_s * clip_rate) + clip_rate, dtype=np.float32)
    active = np.zeros(vocal.size, dtype=np.bool_)

    centres = {
        voice: _voice_centre(plan, voice, cache, fallback=57.0 if gender == "f" else 46.0)
        + _SINGING_OFFSET_SEMITONES
        for gender, voice in plan.voices.items()
    }
    ladders = {voice: _ladder(arrangement.key, centre) for voice, centre in centres.items()}
    truth: list[TruthLine] = []

    for line in plan.lines:
        truth_line = TruthLine(singer=line.singer, paragraph=line.paragraph, text=line.text)
        voices = _voices_for(line.singer, plan.voices)
        for token in line.tokens:
            starts: list[int] = []
            ends: list[int] = []
            midi_notes: list[int] = []
            origin = round(token.start_s * clip_rate)
            for voice in voices:
                notes, centre_index = ladders[voice]
                midi = notes[int(np.clip(centre_index + token.step, 0, len(notes) - 1))]
                clip = trim_to_active(cache.get(token.core, token.language, voice), clip_rate)
                audio = render_note(
                    clip,
                    clip_rate,
                    NoteSpec(
                        midi=float(midi),
                        duration_s=token.sound_s,
                        glide_cents=token.glide_cents,
                        detune_cents=token.detune_cents,
                        vibrato_cents=45.0 if token.vibrato else 0.0,
                        fade_out_ms=1000.0 * _LEGATO_OVERLAP_S if token.legato else 12.0,
                    ),
                )
                bounds = active_bounds(audio, clip_rate)
                if bounds is None:
                    raise RuntimeError(f"TTS produced silence for {token.core!r} ({voice})")
                gain = np.float32(0.75 if len(voices) > 1 else 1.0)
                end = min(vocal.size, origin + audio.size)
                vocal[origin:end] += audio[: end - origin] * gain
                starts.append(origin + bounds[0])
                ends.append(origin + bounds[1])
                midi_notes.append(midi)
            start, end = min(starts), max(ends)
            active[start:end] = True
            truth_line.tokens.append(
                TruthToken(
                    text=token.text,
                    start_ms=round(start * 1000 / clip_rate),
                    end_ms=round(end * 1000 / clip_rate),
                    midi=midi_notes[0],
                )
            )
        truth.append(truth_line)

    # Vocal level: -20 dBFS RMS over the sounding samples.
    sounding_rms = float(np.sqrt(np.mean(vocal[active].astype(np.float64) ** 2)))
    vocal *= np.float32(0.1 / sounding_rms)
    vocal_48k = upsample(vocal, clip_rate, OUTPUT_RATE)

    band_rng = np.random.default_rng([_SALT, 7, _LANGUAGE_INDEX[plan.language], plan.seed])
    band = render_accompaniment(arrangement, OUTPUT_RATE, band_rng)
    length = min(vocal_48k.size, band.shape[0])
    vocal_48k, band = vocal_48k[:length], band[:length]
    wet = _reverb(vocal_48k, OUTPUT_RATE, band_rng)
    vocal_stereo = np.stack([vocal_48k, vocal_48k], axis=1) + wet
    band_rms = float(np.sqrt(np.mean(band.astype(np.float64) ** 2)))

    mixes: dict[int, Path] = {}
    for snr in snr_levels:
        band_gain = 0.1 / (band_rms * 10.0 ** (snr / 20.0))
        mix = vocal_stereo + band * np.float32(band_gain)
        peak = float(np.abs(mix).max())
        if peak > 0.89:
            mix = mix * np.float32(0.89 / peak)
        path = directory / f"mix_snr{snr:02d}.wav"
        sf.write(path, mix, OUTPUT_RATE, subtype="PCM_16")
        mixes[snr] = path

    vocals_path = directory / "vocals_dry.wav"
    sf.write(vocals_path, vocal_48k, OUTPUT_RATE, subtype="PCM_16")

    lyrics_path = directory / "lyrics.txt"
    lyrics_path.write_text(lyrics_text(plan), encoding="utf-8")
    duration_ms = round(length * 1000 / OUTPUT_RATE)
    truth_path = directory / "truth.json"
    truth_path.write_text(
        json.dumps(
            {
                "generator_version": GENERATOR_VERSION,
                "song_id": plan.song_id,
                "language": plan.language,
                "seed": plan.seed,
                "title": plan.title,
                "duration_ms": duration_ms,
                "bpm": arrangement.bpm,
                "key": arrangement.key,
                "voices": plan.voices,
                "sections": [asdict(section) for section in arrangement.sections],
                "lines": [asdict(line) for line in truth],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return RenderedSong(directory, lyrics_path, truth_path, vocals_path, mixes, duration_ms)


def lyrics_text(plan: SongPlan) -> str:
    """The song's lyrics in KaraForge's ``.txt`` format."""
    rows = [
        f"# title: {plan.title}",
        "# artist: KaraForge Synth",
        "# lyricist: KaraForge contributors",
        "# composer: kfbench",
    ]
    paragraph = -1
    singer: str | None = None
    for line in plan.lines:
        if line.paragraph != paragraph:
            rows.append("")
            paragraph = line.paragraph
        tag = f"[{_SINGER_TAGS[line.singer]}] " if line.singer != singer else ""
        singer = line.singer
        rows.append(f"{tag}{line.text}")
    return "\n".join(rows) + "\n"
