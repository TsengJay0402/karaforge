"""Optional stage: pitch track of the vocal stem (needed only by the UltraStar export)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import numpy as np

from karaforge.audio.io import read_mono
from karaforge.audio.pitch import PITCH_VERSION, estimate_f0, save_f0
from karaforge.pipeline.stage import JsonDict, Stage, StageContext, StageInputs

F0_FILE = "f0.npz"


class PitchStage(Stage):
    """Track the sung pitch with pYIN."""

    name: ClassVar[str] = "pitch"
    version: ClassVar[str] = PITCH_VERSION
    requires: ClassVar[tuple[str, ...]] = ("separate",)
    weight: ClassVar[float] = 0.5
    title_zh: ClassVar[str] = "分析音高"
    title_en: ClassVar[str] = "Tracking pitch"

    def inputs(self, ctx: StageContext) -> StageInputs:
        """Only the vocal stem."""
        return StageInputs(files={"vocals": ctx.paths.media / "vocals.wav"})

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Run pYIN over the whole stem."""
        ctx.progress(0.0, "分析音高 / tracking pitch")
        f0 = estimate_f0(read_mono(ctx.paths.media / "vocals.wav"))
        save_f0(out_dir / F0_FILE, f0)
        voiced = np.isfinite(f0)
        return {
            "frames": int(f0.size),
            "voiced_share": round(float(voiced.mean()), 3) if f0.size else 0.0,
            "median_hz": round(float(np.median(f0[voiced])), 1) if voiced.any() else None,
        }

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Nothing to publish: the pitch track is read from the cache by the exporter."""
