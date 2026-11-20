"""Stage ② separate: split the mix into a vocal stem and the karaoke accompaniment."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import numpy as np

from karaforge.adapters.registry import create_separator
from karaforge.audio.io import read_wav
from karaforge.audio.peaks import PEAKS_VERSION, write_peaks
from karaforge.device import resolve_device
from karaforge.pipeline.stage import (
    JsonDict,
    Stage,
    StageContext,
    StageInputs,
    link_or_copy,
    update_project,
)
from karaforge.project.schema import Project
from karaforge.runtime import subprogress


class SeparateStage(Stage):
    """Run the configured separator on ``audio.wav``."""

    name: ClassVar[str] = "separate"
    version: ClassVar[str] = "1"
    requires: ClassVar[tuple[str, ...]] = ("ingest",)
    weight: ClassVar[float] = 5.0
    cache_keep: ClassVar[int] = 2
    title_zh: ClassVar[str] = "分離人聲與伴奏"
    title_en: ClassVar[str] = "Separating vocals"

    def inputs(self, ctx: StageContext) -> StageInputs:
        """The analysis audio and the separator identity."""
        separator = create_separator(ctx.profile.separate, resolve_device(ctx.profile.device))
        return StageInputs(
            files={"audio": ctx.paths.media / "audio.wav"},
            params={"peaks": PEAKS_VERSION},
            adapters={"separator": separator.info.tag},
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Separate and compute peaks of the vocal stem for the editor's timeline."""
        device = resolve_device(ctx.profile.device)
        separator = create_separator(ctx.profile.separate, device)
        result = separator.separate(
            ctx.paths.media / "audio.wav",
            out_dir,
            progress=subprogress(ctx.progress, 0.0, 0.95),
            cancel=ctx.cancel,
        )
        vocals, rate = read_wav(result.vocals)
        mono = np.asarray(vocals.mean(axis=1), dtype=np.float32)
        write_peaks(out_dir / "vocals.peaks.json", mono, rate)
        return {
            "separator": separator.info.tag,
            "device": device.kind,
            "vocals_rms": float(np.sqrt(np.mean(mono.astype(np.float64) ** 2))),
        }

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Expose the stems under ``media/``."""
        for name in ("vocals.wav", "instrumental.wav", "vocals.peaks.json"):
            link_or_copy(out_dir / name, ctx.paths.media / name)

        def mutate(project: Project) -> None:
            project.media.vocals = "media/vocals.wav"
            project.media.instrumental = "media/instrumental.wav"

        update_project(ctx, mutate)
