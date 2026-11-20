"""Forced alignment with wav2vec2 CTC models.

Three models are supported (see the registry for licences):

``wav2vec2-zh``
    Character-level Chinese model.  Its vocabulary is thousands of characters, and which of
    several homophones it prefers depends on context it never saw in lyrics.  Instead of
    asking "where is the character 星?", the aligner therefore asks "where is the syllable
    *xing*?" by **pooling the probability of every character with that reading** — the model
    is used as a syllable recogniser.

``wav2vec2-en``
    Letter-level English model; words are spelled out.

``mms-fa``
    Meta's multilingual alignment model, which takes romanised text for every language
    (pinyin letters for Chinese).  One model for everything, but CC-BY-NC.

With ``align.model = "default"`` the Chinese model handles Chinese characters and the English
model everything else, so the default set-up uses only permissively licensed weights.  Both
models produce one frame per 20 ms on the same grid, which makes it possible to align a line
that mixes the two languages in a single pass: each token takes its probabilities from the
model that can spell it.

Sound inside the window that does not belong to the line (a neighbouring line's tail) and
tokens the model has no symbols for are matched by a wildcard column, see
:func:`karaforge.align.ctc.wildcard_column`.

The acoustic model does not depend on the text, so it runs **once per song**
(:meth:`CtcAligner.prepare`); each line then only needs a Viterbi pass over its slice of the
stored frame probabilities.  Re-aligning after the user locked a few tokens therefore takes a
fraction of a second.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from karaforge.adapters import pool
from karaforge.adapters.base import AdapterInfo, AlignRequest, AlignUnit, UnitTiming
from karaforge.align.ctc import (
    F32,
    forced_align,
    log_softmax,
    pooled_column,
    wildcard_column,
)
from karaforge.audio.io import MODEL_RATE, FloatArray
from karaforge.device import DeviceChoice, cpu_threads
from karaforge.errors import DependencyMissingError
from karaforge.models import store
from karaforge.models.registry import get_model
from karaforge.text.romanize import to_simplified, word_reading
from karaforge.text.tokenize import TokenKind, is_han

FRAME_S = 0.02
_STRIDE = 320
"""Samples between two output frames of wav2vec2 (20 ms at 16 kHz)."""
_MIN_SAMPLES = 400
"""Receptive field of one frame."""
_CHUNK_FRAMES = 1000
_MARGIN_FRAMES = 100
_KEPT_SONGS = 2
"""Songs whose frame probabilities are kept in memory (per model)."""
DEFAULT_MODELS = ("wav2vec2-zh", "wav2vec2-en")
_LAG_S: dict[tuple[str, bool], float] = {
    ("wav2vec2-zh", True): 0.03,
    ("wav2vec2-zh", False): 0.03,
    ("wav2vec2-en", True): 0.10,
    ("wav2vec2-en", False): 0.10,
    ("mms-fa", True): 0.02,
    ("mms-fa", False): 0.05,
}
"""How long after a token begins the model's output for it fires, per ``(model, token is a
Chinese character)``; subtracted from every time.  The values were measured on the benchmark's
development songs (never on the test songs).  Words lag more than single syllables because
their letters fire in a burst well after the word has begun."""
_LANGUAGES: dict[str, tuple[str, ...]] = {
    "wav2vec2-zh": ("zh", "cmn", "mixed"),
    "wav2vec2-en": ("en",),
    "mms-fa": ("*",),
}


@dataclass(frozen=True)
class _Vocabulary:
    """What a model's output columns mean."""

    blank: int
    silent: tuple[int, ...]
    """Columns that, like the blank, stand for "no sound here": the word delimiter ``|``
    that these models emit in the gaps between words, and sentence markers."""
    letters: dict[str, int]
    """Latin letters (lower-case key) and the apostrophe."""
    characters: dict[str, int]
    """Single Chinese characters."""
    syllables: dict[str, tuple[int, ...]]
    """Toneless pinyin syllable → columns of every character that can be read that way."""

    @property
    def spells(self) -> bool:
        """Whether the model has (nearly) the whole Latin alphabet."""
        return sum(1 for letter in "abcdefghijklmnopqrstuvwxyz" if letter in self.letters) >= 24


def _read_vocabulary(vocab: dict[str, int]) -> _Vocabulary:
    from pypinyin import Style, pinyin

    blank = next((vocab[name] for name in ("<blank>", "<pad>", "[PAD]") if name in vocab), 0)
    silent = tuple(
        sorted({vocab[name] for name in ("|", " ", "<s>", "</s>") if name in vocab} - {blank})
    )
    letters: dict[str, int] = {}
    characters: dict[str, int] = {}
    for symbol, column in vocab.items():
        if len(symbol) != 1:
            continue
        if symbol.isascii() and (symbol.isalpha() or symbol == "'"):
            # Prefer the case the model was trained with; either maps to the same key.
            letters.setdefault(symbol.lower(), column)
        elif is_han(symbol):
            characters[symbol] = column
    syllables: dict[str, list[int]] = {}
    for character, column in characters.items():
        readings: list[str] = pinyin(character, style=Style.NORMAL, heteronym=True, v_to_u=False)[0]
        for reading in readings:
            if reading.isascii() and reading.isalpha():
                syllables.setdefault(reading, []).append(column)
    return _Vocabulary(
        blank=blank,
        silent=silent,
        letters=letters,
        characters=characters,
        syllables={key: tuple(sorted(set(value))) for key, value in syllables.items()},
    )


class _Wav2Vec2:
    """A loaded wav2vec2 CTC model that turns audio into frame-wise log-probabilities."""

    def __init__(self, model_id: str, device: DeviceChoice) -> None:
        try:
            import torch
            from transformers import Wav2Vec2ForCTC
        except ImportError as exc:
            raise DependencyMissingError(
                "缺少 transformers / torch,無法使用 CTC 對齊器。",
                "transformers / torch are missing; the CTC aligner is unavailable.",
                hint_zh="請執行:uv sync --extra cpu",
                hint_en="Run: uv sync --extra cpu",
                detail=str(exc),
            ) from exc
        directory = store.ensure(model_id)
        self._torch: Any = torch
        self._device = device.kind
        if device.kind == "cpu":
            torch.set_num_threads(cpu_threads())
        loader: Any = Wav2Vec2ForCTC
        model: Any = loader.from_pretrained(str(directory), local_files_only=True)
        self._model = model.to(device.kind).eval()
        vocab: dict[str, int] = json.loads((directory / "vocab.json").read_text(encoding="utf-8"))
        self.vocabulary = _read_vocabulary(vocab)
        config = json.loads((directory / "preprocessor_config.json").read_text(encoding="utf-8"))
        self._normalize = bool(config.get("do_normalize", True))
        self._songs: OrderedDict[str, F32] = OrderedDict()

    def song_log_probs(self, key: str, samples: FloatArray) -> F32:
        """Frame probabilities of a whole recording, computed once and remembered by ``key``."""
        cached = self._songs.get(key)
        if cached is None:
            cached = self.log_probs(samples)
            self._songs[key] = cached
            while len(self._songs) > _KEPT_SONGS:
                self._songs.popitem(last=False)
        else:
            self._songs.move_to_end(key)
        return cached

    def _forward(self, samples: FloatArray) -> F32:
        torch = self._torch
        signal = samples.astype(np.float32)
        if self._normalize:
            signal = (signal - signal.mean()) / np.sqrt(signal.var() + 1e-7)
        with torch.inference_mode():
            batch = torch.from_numpy(signal).unsqueeze(0).to(self._device)
            logits = self._model(batch).logits[0]
        return log_softmax(np.asarray(logits.float().cpu().numpy(), dtype=np.float32))

    def log_probs(self, samples: FloatArray) -> F32:
        """Frame-wise log-probabilities (one row per 20 ms) for 16 kHz mono ``samples``.

        Long input is processed in 20-second pieces, each computed with two seconds of
        context on both sides, because the transformer's memory use grows with the square
        of the length.  Pieces start on frame boundaries, so the rows line up exactly.
        """
        if samples.size < _MIN_SAMPLES:
            return np.zeros((0, 1), dtype=np.float32)
        total = (samples.size - _MIN_SAMPLES) // _STRIDE + 1
        if total <= _CHUNK_FRAMES + 2 * _MARGIN_FRAMES:
            return self._forward(samples)[:total]
        pieces: list[F32] = []
        for first in range(0, total, _CHUNK_FRAMES):
            last = min(total, first + _CHUNK_FRAMES)
            block_first = max(0, first - _MARGIN_FRAMES)
            block_last = min(total, last + _MARGIN_FRAMES)
            block = self._forward(
                samples[block_first * _STRIDE : (block_last - 1) * _STRIDE + _MIN_SAMPLES]
            )
            pieces.append(block[first - block_first : last - block_first])
        return np.concatenate(pieces, axis=0)[:total]


def _columns_for(unit: AlignUnit, vocabulary: _Vocabulary) -> list[tuple[int, ...]] | None:
    """Model columns that spell ``unit`` (each entry is pooled), or ``None`` if unknown."""
    if unit.kind is TokenKind.HAN and vocabulary.characters:
        if unit.reading and unit.reading in vocabulary.syllables:
            return [vocabulary.syllables[unit.reading]]
        columns = [
            vocabulary.characters[char]
            for char in to_simplified(unit.text)
            if char in vocabulary.characters
        ]
        return [(column,) for column in columns] or None
    if not vocabulary.spells:
        return None
    reading = unit.reading or word_reading(unit.text)
    spelled = [
        (vocabulary.letters[letter],)
        for letter in reading.replace("v", "u")
        if letter in vocabulary.letters
    ]
    return spelled or None


class CtcAligner:
    """Aligner based on wav2vec2 CTC posteriors and Viterbi alignment.

    Args:
        model: ``default`` (Chinese + English pair) or a single registry id.
        device: Resolved compute device.
    """

    max_window_s: float | None = None
    weak_score: float = 0.3
    """Below this evidence the model did not hear the token (see :func:`_evidence`)."""

    def __init__(self, model: str, device: DeviceChoice) -> None:
        self._models = DEFAULT_MODELS if model == "default" else (model,)
        self._device = device
        self._song: FloatArray | None = None
        self._song_key = ""
        specs = [get_model(model_id) for model_id in self._models]
        languages: set[str] = set()
        for model_id in self._models:
            languages.update(_LANGUAGES.get(model_id, ("*",)))
        self._info = AdapterInfo(
            name="ctc",
            version="7+" + "+".join(self._models),
            license=" / ".join(sorted({spec.license for spec in specs})),
            languages=("*",)
            if "*" in languages or len(self._models) > 1
            else tuple(sorted(languages)),
            devices=("cpu", "cuda", "mps"),
            memory_mb=1800 * len(self._models),
            description_zh="wav2vec2 CTC 強制對齊(" + "、".join(spec.title for spec in specs) + ")",
            description_en="wav2vec2 CTC forced alignment ("
            + ", ".join(s.title for s in specs)
            + ")",
            models=self._models,
        )

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        return self._info

    def _model(self, model_id: str) -> _Wav2Vec2:
        return pool.shared(
            ("wav2vec2-ctc", model_id, self._device.kind),
            lambda: _Wav2Vec2(model_id, self._device),
        )

    def _models_of(self, units: list[AlignUnit]) -> list[str]:
        """Which model spells each unit.

        With the default pair, Chinese characters go to the Chinese model and everything
        else to the English one — also inside one line, so a line that mixes the two
        languages is aligned with both models at once.
        """
        if len(self._models) == 1:
            return [self._models[0]] * len(units)
        chinese, other = self._models[0], self._models[1]
        return [chinese if unit.kind is TokenKind.HAN else other for unit in units]

    def prepare(self, audio: FloatArray) -> None:
        """Remember the whole stem; its frame probabilities are computed on first use."""
        self._song = audio
        self._song_key = hashlib.blake2b(audio.tobytes(), digest_size=16).hexdigest()

    def _window_log_probs(self, model: _Wav2Vec2, request: AlignRequest) -> tuple[F32, float]:
        """Frame probabilities for the request's window and the time of the first row.

        When the window is a slice of the prepared stem the rows are cut out of the stem's
        stored probabilities; otherwise the model runs on the window itself.
        """
        song = self._song
        if song is None or request.offset_s is None:
            return model.log_probs(request.audio), 0.0
        first_sample = round(request.offset_s * MODEL_RATE)
        last_sample = first_sample + request.audio.size
        if first_sample < 0 or last_sample > song.size:
            return model.log_probs(request.audio), 0.0
        whole = model.song_log_probs(self._song_key, song)
        first = -(-first_sample // _STRIDE)  # first frame that starts inside the window
        last = min(whole.shape[0], max(first, (last_sample - _MIN_SAMPLES) // _STRIDE + 1))
        return whole[first:last], first * FRAME_S - request.offset_s

    def align(self, request: AlignRequest) -> list[UnitTiming]:
        """Align the units of ``request`` to its audio window."""
        units = list(request.units)
        if not units:
            return []
        duration = request.audio.size / MODEL_RATE
        unit_models = self._models_of(units)
        vocabularies: dict[str, _Vocabulary] = {}
        log_probs: dict[str, F32] = {}
        origin = 0.0
        for model_id in dict.fromkeys(unit_models):
            model = self._model(model_id)
            vocabularies[model_id] = model.vocabulary
            log_probs[model_id], origin = self._window_log_probs(model, request)
        frames = min(matrix.shape[0] for matrix in log_probs.values())
        if frames == 0:
            return _spread(len(units), duration)

        # A small emission matrix is assembled from the models' outputs: per model a
        # "nothing" column (blank, plus the word delimiter that fires in the gaps between
        # syllables) and a wildcard column, then one column per target symbol.
        columns: list[F32] = []
        nothing: dict[str, int] = {}
        wildcard: dict[str, int] = {}
        for model_id, matrix in log_probs.items():
            vocabulary = vocabularies[model_id]
            silent = pooled_column(matrix[:frames], (vocabulary.blank, *vocabulary.silent))
            nothing[model_id] = len(columns)
            columns.append(silent)
            wildcard[model_id] = len(columns)
            columns.append(wildcard_column(silent))
        between: dict[tuple[str, str], int] = {}

        def gap(left: str, right: str) -> int:
            """Blank column for the gap between a token of ``left`` and one of ``right``."""
            if left == right:
                return nothing[left]
            key = (left, right) if left < right else (right, left)
            if key not in between:
                between[key] = len(columns)
                columns.append(
                    (0.5 * (columns[nothing[left]] + columns[nothing[right]])).astype(np.float32)
                )
            return between[key]

        pooled: dict[tuple[str, tuple[int, ...]], int] = {}
        targets: list[int] = []
        owner: list[int] = []
        blanks: list[int] = []
        target_models: list[str] = []

        def push(column: int, unit_index: int, model_id: str) -> None:
            blanks.append(gap(target_models[-1] if target_models else model_id, model_id))
            targets.append(column)
            owner.append(unit_index)
            target_models.append(model_id)

        if request.open_start:
            push(wildcard[unit_models[0]], -1, unit_models[0])
        for index, (unit, model_id) in enumerate(zip(units, unit_models, strict=True)):
            spelled = _columns_for(unit, vocabularies[model_id])
            if spelled is None:
                # Consecutive units the model cannot spell share one wildcard.
                if not targets or targets[-1] != wildcard[model_id] or owner[-1] == -1:
                    push(wildcard[model_id], index, model_id)
                continue
            for group in spelled:
                key = (model_id, group)
                if key not in pooled:
                    pooled[key] = len(columns)
                    columns.append(pooled_column(log_probs[model_id][:frames], group))
                push(pooled[key], index, model_id)
        if request.open_end and targets and targets[-1] != wildcard[unit_models[-1]]:
            push(wildcard[unit_models[-1]], -1, unit_models[-1])
        blanks.append(nothing[target_models[-1]])

        spans = forced_align(np.stack(columns, axis=1), targets, blank=blanks)
        if spans is None:
            return _spread(len(units), duration)

        wild = set(wildcard.values())
        first_frame: dict[int, int] = {}
        last_frame: dict[int, int] = {}
        identity: dict[int, list[float]] = {}
        for span, unit_index, target in zip(spans, owner, targets, strict=True):
            if unit_index < 0:
                continue
            first_frame.setdefault(unit_index, span.start_frame)
            last_frame[unit_index] = span.end_frame
            identity.setdefault(unit_index, []).append(0.0 if target in wild else span.score)
        heard = {
            model_id: 1.0 - np.exp(columns[column].astype(np.float64))
            for model_id, column in nothing.items()
        }
        scores = _evidence(first_frame, last_frame, identity, [heard[m] for m in unit_models])

        timings: list[UnitTiming] = []
        previous_end = 0.0
        for index, model_id in enumerate(unit_models):
            if index in first_frame:
                lag = _LAG_S.get((model_id, units[index].kind is TokenKind.HAN), 0.0)
                start = max(0.0, origin + first_frame[index] * FRAME_S - lag)
                end = max(start, min(duration, origin + last_frame[index] * FRAME_S - lag))
            else:
                # A unit that shared a wildcard with its neighbour: it has no span of its own.
                start = end = previous_end
            timings.append(
                UnitTiming(
                    start_s=min(start, duration), end_s=min(end, duration), score=scores[index]
                )
            )
            previous_end = end
        return timings


def _evidence(
    first_frame: dict[int, int],
    last_frame: dict[int, int],
    identity: dict[int, list[float]],
    heard: list[npt.NDArray[np.float64]],
) -> list[float]:
    """How much the acoustic model supports each unit's position, in ``[0, 1]``.

    Two questions are asked:

    * *Did the model hear a syllable where the unit was placed?*  The probability that the
      unit's frames are not blank.  A sung syllable is often mistaken for a similar-sounding
      one, so "what" is unreliable, but "that something starts here" is not.
    * *Is the unit merely squeezed in?*  When the model hears nothing for a unit, the forced
      alignment still has to put it somewhere and parks it on the frames next to a
      neighbour's syllable.  A unit that touches a neighbour without a blank frame in between
      and matches its frames worse than that neighbour gets only the (low) probability of
      its own symbols.

    Args:
        first_frame: First frame of each unit that got a span.
        last_frame: One past its last frame.
        identity: Probabilities of the unit's own symbols on their frames.
        heard: Per unit, the frame-wise probability that its model heard anything at all.
    """
    match = {index: float(np.mean(values)) for index, values in identity.items()}
    scores: list[float] = []
    for index, audible in enumerate(heard):
        if index not in first_frame:
            scores.append(0.0)
            continue
        low, high = first_frame[index], max(last_frame[index], first_frame[index] + 1)
        presence = float(audible[low:high].max()) if high <= audible.size else 0.0
        squeezed = False
        for neighbour in (index - 1, index + 1):
            if neighbour not in first_frame:
                continue
            touching = (
                last_frame[neighbour] == low
                if neighbour < index
                else first_frame[neighbour] == high
            )
            if touching and match[index] < match[neighbour]:
                squeezed = True
        scores.append(min(1.0, match[index] if squeezed else max(match[index], presence)))
    return scores


def _spread(count: int, duration: float) -> list[UnitTiming]:
    """Evenly spaced timings with zero confidence (used when alignment is impossible)."""
    step = duration / count if count else 0.0
    return [UnitTiming(index * step, (index + 1) * step, 0.0) for index in range(count)]
