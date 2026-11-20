"""Stage: analyse the stems — voice activity, onsets, tempo and beats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from karaforge.align.features import FEATURES_VERSION, HOP_S, VocalFeatures, compute_features
from karaforge.audio.io import read_mono
from karaforge.pipeline.stage import (
    JsonDict,
    Stage,
    StageContext,
    StageInputs,
    update_project,
)
from karaforge.project.schema import Project

_BEAT_RATE = 22050
FEATURES_FILE = "features.npz"


def save_features(path: Path, features: VocalFeatures) -> None:
    """Store vocal features as a compressed ``.npz`` file."""
    np.savez_compressed(
        path,
        energy_db=features.energy_db,
        flatness=features.flatness,
        onset_strength=features.onset_strength,
        onsets_s=features.onsets_s,
        onset_peaks=features.onset_peaks,
        regions_s=np.asarray(features.regions_s, dtype=np.float64).reshape(-1, 2),
        scalars=np.asarray([features.noise_floor_db, features.active_threshold_db]),
    )


def load_features(path: Path) -> VocalFeatures:
    """Load vocal features written by :func:`save_features`."""
    with np.load(path) as data:
        regions = np.asarray(data["regions_s"], dtype=np.float64).reshape(-1, 2)
        scalars = np.asarray(data["scalars"], dtype=np.float64)
        return VocalFeatures(
            energy_db=np.asarray(data["energy_db"], dtype=np.float32),
            flatness=np.asarray(data["flatness"], dtype=np.float32),
            onset_strength=np.asarray(data["onset_strength"], dtype=np.float32),
            onsets_s=np.asarray(data["onsets_s"], dtype=np.float64),
            onset_peaks=np.asarray(data["onset_peaks"], dtype=np.float32),
            regions_s=tuple((float(row[0]), float(row[1])) for row in regions),
            noise_floor_db=float(scalars[0]),
            active_threshold_db=float(scalars[1]),
        )


def estimate_beats(path: Path) -> tuple[float | None, list[int]]:
    """Estimate tempo (BPM) and beat times (ms) of an audio file with librosa.

    Returns ``(None, [])`` when no stable beat is found (e.g. a cappella or very short audio).
    """
    import librosa

    signal = read_mono(path, _BEAT_RATE)
    if signal.size < _BEAT_RATE * 4:
        return None, []
    tempo_raw, beat_times = librosa.beat.beat_track(y=signal, sr=_BEAT_RATE, units="time")
    tempo_values = np.atleast_1d(np.asarray(tempo_raw, dtype=np.float64))
    tempo = float(tempo_values[0]) if tempo_values.size else 0.0
    beats = [round(float(value) * 1000) for value in np.asarray(beat_times, dtype=np.float64)]
    if tempo <= 0.0 or len(beats) < 4:
        return None, []
    return tempo, beats


class AnalyzeStage(Stage):
    """Compute vocal features and the song's beat grid."""

    name: ClassVar[str] = "analyze"
    version: ClassVar[str] = "1"
    requires: ClassVar[tuple[str, ...]] = ("separate",)
    weight: ClassVar[float] = 0.5
    title_zh: ClassVar[str] = "分析人聲與節拍"
    title_en: ClassVar[str] = "Analysing vocals and beat"

    def inputs(self, ctx: StageContext) -> StageInputs:
        """Both stems and the analysis parameters."""
        settings = ctx.profile.analyze
        return StageInputs(
            files={
                "vocals": ctx.paths.media / "vocals.wav",
                "instrumental": ctx.paths.media / "instrumental.wav",
            },
            params={
                "features": FEATURES_VERSION,
                "vad": settings.vad,
                "onset": settings.onset,
                "min_region_ms": settings.vad_min_region_ms,
                "merge_gap_ms": settings.vad_merge_gap_ms,
            },
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Extract features from the vocal stem and beats from the accompaniment."""
        settings = ctx.profile.analyze
        vocals = read_mono(ctx.paths.media / "vocals.wav")
        ctx.progress(0.1, "偵測人聲與起音 / detecting voice and onsets")
        features = compute_features(
            vocals,
            min_region_ms=settings.vad_min_region_ms,
            merge_gap_ms=settings.vad_merge_gap_ms,
        )
        save_features(out_dir / FEATURES_FILE, features)
        ctx.cancel.raise_if_cancelled()
        ctx.progress(0.5, "估計節拍 / estimating tempo")
        tempo, beats = estimate_beats(ctx.paths.media / "instrumental.wav")
        result: dict[str, Any] = {
            "hop_ms": round(HOP_S * 1000),
            "vocal_regions": [
                [round(start * 1000), round(end * 1000)] for start, end in features.regions_s
            ],
            "onsets_ms": [round(float(value) * 1000) for value in features.onsets_s],
            "tempo_bpm": tempo,
            "beats_ms": beats,
        }
        (out_dir / "analysis.json").write_text(json.dumps(result), encoding="utf-8")
        return result

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Store regions, tempo and beats in the project; expose onsets for the editor."""
        target = ctx.paths.media / "analysis.json"
        target.write_text((out_dir / "analysis.json").read_text(encoding="utf-8"), encoding="utf-8")

        def mutate(project: Project) -> None:
            tempo = result.get("tempo_bpm")
            project.analysis.tempo_bpm = float(tempo) if tempo else None
            project.analysis.beats_ms = [int(value) for value in result.get("beats_ms", [])]
            project.analysis.vocal_regions = [
                (int(pair[0]), int(pair[1])) for pair in result.get("vocal_regions", [])
            ]

        update_project(ctx, mutate)
