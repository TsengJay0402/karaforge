"""Forced alignment from Whisper's cross-attention.

Whisper's decoder attends to the audio frames that correspond to the token it is emitting.
Feeding the *known* lyric tokens through the decoder and running dynamic time warping over
the attention weights yields a start time for every token (20 ms resolution).  This is the
mechanism behind Whisper's own word timestamps, used here with the reference text instead
of a recognised one.

It needs no model beyond the Whisper weights that the speech-recognition stage already
loaded, works for any language Whisper knows and handles mixed Chinese/English lines
natively, which makes it the light-weight default aligner.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from karaforge.adapters.asr.faster_whisper import load_whisper, whisper_language
from karaforge.adapters.base import AdapterInfo, AlignRequest, UnitTiming
from karaforge.audio.io import MODEL_RATE, FloatArray
from karaforge.device import DeviceChoice
from karaforge.errors import AlignmentError
from karaforge.models.registry import get_model
from karaforge.text.tokenize import TokenKind

_MAX_WINDOW_S = 29.5
_FRAME_S = 0.02


class WhisperAttentionAligner:
    """Aligner based on Whisper cross-attention and DTW.

    Args:
        model_id: Registry id of the Whisper model, e.g. ``whisper-small``.
        device: Resolved compute device.
    """

    def __init__(self, model_id: str, device: DeviceChoice) -> None:
        spec = get_model(model_id)
        self._model_id = model_id
        self._device = device
        self._info = AdapterInfo(
            name="whisper-attn",
            version=f"1+{model_id}",
            license=spec.license,
            languages=("*",),
            devices=("cpu", "cuda"),
            memory_mb=1000,
            description_zh=f"Whisper 交叉注意力強制對齊({spec.title})",
            description_en=f"Whisper cross-attention forced alignment ({spec.title})",
            models=(model_id,),
        )

    @property
    def info(self) -> AdapterInfo:
        """Adapter self-description."""
        return self._info

    def align(self, request: AlignRequest) -> list[UnitTiming]:
        """Align the units of ``request`` to its audio window (at most ~30 s)."""
        units = list(request.units)
        if not units:
            return []
        duration = request.audio.size / MODEL_RATE
        if duration > _MAX_WINDOW_S:
            raise AlignmentError(
                "這一行的時間窗超過 Whisper 對齊器的 30 秒上限。",
                "The line's window exceeds the 30-second limit of the Whisper aligner.",
                hint_zh="請把這一行拆短,或改用 CTC 對齊器(align.aligner=ctc)。",
                hint_en="Split the line or use the CTC aligner (align.aligner=ctc).",
                detail=f"window {duration:.1f}s",
            )
        model = load_whisper(self._model_id, self._device)
        tokenizer = _tokenizer(model, whisper_language(request.language) or "zh")

        # Neighbouring lines' tokens are aligned too, so that their sound inside the padded
        # window is not attributed to this line; only this line's timings are returned.
        prefix = list(request.prefix_units)
        sequence = [*prefix, *units, *request.suffix_units]
        token_ids: list[int] = []
        first_token: list[int] = []
        previous_kind: TokenKind | None = None
        for unit in sequence:
            needs_space = unit.kind is TokenKind.WORD and previous_kind is not None
            piece = (" " if needs_space else "") + unit.text
            encoded: list[int] = [int(t) for t in tokenizer.encode(piece)]
            if not encoded:
                encoded = [int(t) for t in tokenizer.encode(" " + unit.text)]
            first_token.append(len(token_ids))
            token_ids.extend(encoded)
            previous_kind = unit.kind
        if not token_ids:
            return [UnitTiming(0.0, 0.0, 0.0) for _ in units]

        starts, probabilities = _token_times(model, tokenizer, request.audio, token_ids)
        boundaries = [*first_token, len(token_ids)]
        timings: list[UnitTiming] = []
        for index in range(len(prefix), len(prefix) + len(units)):
            begin, end = boundaries[index], boundaries[index + 1]
            start_s = float(starts[begin])
            end_s = float(starts[end])
            score = float(np.mean(probabilities[begin:end])) if end > begin else 0.0
            timings.append(
                UnitTiming(
                    start_s=min(start_s, duration),
                    end_s=min(max(end_s, start_s), duration),
                    score=float(np.clip(score, 0.0, 1.0)),
                )
            )
        return timings


def _tokenizer(model: Any, language: str) -> Any:
    from faster_whisper.tokenizer import Tokenizer

    multilingual = bool(model.model.is_multilingual)
    return Tokenizer(
        model.hf_tokenizer,
        multilingual,
        task="transcribe" if multilingual else None,
        language=language if multilingual else None,
    )


def _token_times(
    model: Any, tokenizer: Any, audio: FloatArray, token_ids: list[int]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Run the alignment for one window.

    Returns:
        ``len(token_ids) + 1`` times (the start of every token, then the end of the last
        one) and the probability of each token.
    """
    from faster_whisper.audio import pad_or_trim

    features = model.feature_extractor(audio)
    content_frames = int(features.shape[-1]) - 1
    segment = pad_or_trim(features)
    encoder_output = model.encode(segment)
    num_frames = max(2, min(int(model.feature_extractor.nb_max_frames), content_frames))
    result = model.model.align(
        encoder_output,
        tokenizer.sot_sequence,
        [token_ids],
        num_frames,
        median_filter_width=7,
    )[0]
    pairs: list[tuple[int, int]] = [(int(pair[0]), int(pair[1])) for pair in result.alignments]
    text_indices = np.array([pair[0] for pair in pairs], dtype=np.int64)
    time_indices = np.array([pair[1] for pair in pairs], dtype=np.float64)
    jumps = np.pad(np.diff(text_indices), (1, 0), constant_values=1).astype(bool)
    jump_times = time_indices[jumps] * _FRAME_S
    # One entry per token plus one for the end-of-text marker.
    expected = len(token_ids) + 1
    if jump_times.size < expected:
        last = float(jump_times[-1]) if jump_times.size else 0.0
        jump_times = np.concatenate([jump_times, np.full(expected - jump_times.size, last)])
    token_probabilities: list[float] = [float(value) for value in result.text_token_probs]
    return jump_times[:expected], np.asarray(token_probabilities, dtype=np.float64)
