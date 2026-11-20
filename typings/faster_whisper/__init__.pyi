from collections.abc import Iterable
from typing import Any

import numpy as np
import numpy.typing as npt

class Word:
    start: float
    end: float
    word: str
    probability: float

class Segment:
    start: float
    end: float
    text: str
    words: list[Word] | None
    avg_logprob: float
    no_speech_prob: float

class TranscriptionInfo:
    language: str
    language_probability: float
    duration: float

class _FeatureExtractor:
    nb_max_frames: int
    def __call__(self, waveform: npt.NDArray[np.float32], padding: int = 160) -> npt.NDArray[np.float32]: ...

class WhisperModel:
    model: Any
    hf_tokenizer: Any
    feature_extractor: _FeatureExtractor
    def __init__(
        self,
        model_size_or_path: str,
        device: str = "auto",
        device_index: int | list[int] = 0,
        compute_type: str = "default",
        cpu_threads: int = 0,
        num_workers: int = 1,
        download_root: str | None = None,
        local_files_only: bool = False,
    ) -> None: ...
    def transcribe(
        self,
        audio: str | npt.NDArray[np.float32],
        language: str | None = None,
        task: str = "transcribe",
        beam_size: int = 5,
        condition_on_previous_text: bool = True,
        initial_prompt: str | None = None,
        word_timestamps: bool = False,
        vad_filter: bool = False,
        hotwords: str | None = None,
        temperature: float | list[float] | tuple[float, ...] = ...,
        no_speech_threshold: float | None = 0.6,
        compression_ratio_threshold: float | None = 2.4,
        log_prob_threshold: float | None = -1.0,
    ) -> tuple[Iterable[Segment], TranscriptionInfo]: ...
    def encode(self, features: npt.NDArray[np.float32]) -> Any: ...
