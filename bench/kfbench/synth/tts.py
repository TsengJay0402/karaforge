"""Offline text-to-speech for the synthetic benchmark, with an on-disk clip cache.

Each character or word is synthesised on its own (so that its position in the final song is
known exactly) and cached as a small WAV file keyed by engine, voice, language and text.  The
cache makes generation fast after the first run and, more importantly, reproducible: once a
clip exists it is reused bit-for-bit.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
import numpy.typing as npt
import soundfile as sf

from karaforge import paths
from karaforge.errors import DependencyMissingError

FloatArray = npt.NDArray[np.float32]
TTSLanguage = Literal["zh", "en"]


class TTSBackend(Protocol):
    """A text-to-speech engine that can speak a single character or word."""

    name: str
    version: str
    sample_rate: int

    def synthesize(self, text: str, language: TTSLanguage, voice: str) -> FloatArray:
        """Return mono float32 audio for ``text``."""
        ...


class KokoroTTS:
    """`Kokoro-82M <https://huggingface.co/hexgrad/Kokoro-82M>`_ (Apache-2.0 code and weights).

    Chosen for the benchmark because both the model and its voices are permissively licensed,
    which lets the generated demo material be redistributed, and because it runs quickly on
    a CPU.  Voices are style vectors and work across languages, so mixed-language songs keep
    one timbre.
    """

    name = "kokoro"
    version = "82M-v1.0"
    sample_rate = 24000

    def __init__(self, repo_id: str = "hexgrad/Kokoro-82M") -> None:
        self._repo_id = repo_id
        self._pipelines: dict[str, Any] = {}

    def _pipeline(self, language: TTSLanguage) -> Any:
        if language not in self._pipelines:
            os.environ.setdefault("HF_HOME", str(paths.home_dir() / "hf-cache"))
            try:
                from kokoro import KPipeline
            except ImportError as exc:
                raise DependencyMissingError(
                    "合成測資需要 kokoro 套件。",
                    "The synthetic benchmark needs the kokoro package.",
                    hint_zh="請執行:uv sync --extra cpu --group bench",
                    hint_en="Run: uv sync --extra cpu --group bench",
                    detail=str(exc),
                ) from exc
            code = "z" if language == "zh" else "a"
            self._pipelines[language] = KPipeline(lang_code=code, repo_id=self._repo_id)
        return self._pipelines[language]

    def synthesize(self, text: str, language: TTSLanguage, voice: str) -> FloatArray:
        """Synthesise ``text`` with the given voice."""
        pipeline = self._pipeline(language)
        chunks: list[FloatArray] = []
        for result in pipeline(text, voice=voice, speed=1.0):
            audio = result.audio
            if audio is not None:
                chunks.append(np.asarray(audio.detach().cpu().numpy(), dtype=np.float32))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)


class ClipCache:
    """Synthesises clips on demand and stores them under ``directory``."""

    def __init__(self, backend: TTSBackend, directory: Path) -> None:
        self.backend = backend
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, text: str, language: TTSLanguage, voice: str) -> Path:
        identity = json.dumps(
            [self.backend.name, self.backend.version, voice, language, text], ensure_ascii=False
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return self.directory / f"{self.backend.name}-{voice}-{language}-{digest}.wav"

    def get(self, text: str, language: TTSLanguage, voice: str) -> FloatArray:
        """Return the clip for ``text``, synthesising and caching it when missing."""
        path = self._path(text, language, voice)
        if path.is_file():
            data, _rate = sf.read(path, dtype="float32", always_2d=False)
            return np.asarray(data, dtype=np.float32)
        audio = self.backend.synthesize(text, language, voice)
        temporary = path.with_suffix(".tmp.wav")
        sf.write(temporary, audio, self.backend.sample_rate, subtype="FLOAT")
        temporary.replace(path)
        return audio

    @property
    def sample_rate(self) -> int:
        """Sample rate of the cached clips."""
        return self.backend.sample_rate
