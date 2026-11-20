"""Stage ④ align: the three-pass alignment; writes token times into ``project.json``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from karaforge.adapters.registry import aligner_model, create_aligner
from karaforge.align.engine import ALIGN_ALGORITHM_VERSION, lyric_lines, run_alignment
from karaforge.audio.io import read_mono
from karaforge.device import resolve_device
from karaforge.errors import AlignmentError
from karaforge.pipeline.stage import (
    JsonDict,
    Stage,
    StageContext,
    StageInputs,
    update_project,
)
from karaforge.project.schema import Project
from karaforge.stages.analyze import FEATURES_FILE, load_features
from karaforge.stages.asr import TRANSCRIPT_FILE, load_transcript

ALIGNMENT_FILE = "alignment.json"


def alignment_fingerprint(project: Project, only_lines: list[str] | None) -> dict[str, Any]:
    """The parts of the project that determine the alignment result.

    Text of every token, readings given by the user, the times of locked tokens and line
    times that came from an imported file.  Times of unlocked tokens are deliberately
    excluded: they are this stage's *output*.
    """
    return {
        "language": project.meta.language,
        "only_lines": sorted(only_lines) if only_lines else None,
        "lines": [
            {
                "id": line.id,
                "hint": list(line.time_hint) if line.time_hint is not None else None,
                "tokens": [
                    [
                        token.text,
                        token.ruby if token.ruby_source == "manual" else None,
                        [token.start_ms, token.end_ms] if token.locked else None,
                    ]
                    for token in line.tokens
                ],
            }
            for line in project.lines
        ],
    }


def apply_alignment(
    project: Project, alignment: dict[str, Any], only_lines: list[str] | None = None
) -> int:
    """Write aligned times into ``project`` without touching locked tokens.

    A line is skipped when its text no longer matches what was aligned (it was edited in the
    meantime).

    Returns:
        The number of tokens that were updated.
    """
    by_id: dict[str, Any] = {entry["id"]: entry for entry in alignment.get("lines", [])}
    wanted = set(only_lines) if only_lines else None
    updated = 0
    for line in project.lines:
        entry = by_id.get(line.id)
        if entry is None or (wanted is not None and line.id not in wanted):
            continue
        tokens: list[dict[str, Any]] = entry["tokens"]
        if len(tokens) != len(line.tokens) or any(
            aligned["text"] != token.text
            for aligned, token in zip(tokens, line.tokens, strict=True)
        ):
            continue
        for index, (aligned, token) in enumerate(zip(tokens, line.tokens, strict=True)):
            if token.locked:
                continue
            start, end = int(aligned["start_ms"]), int(aligned["end_ms"])
            line.tokens[index] = token.retimed(
                start, max(start, end), confidence=float(aligned["confidence"]), source="auto"
            )
            updated += 1
    return updated


class AlignStage(Stage):
    """Align the lyrics to the vocal stem and store token times and confidences."""

    name: ClassVar[str] = "align"
    version: ClassVar[str] = ALIGN_ALGORITHM_VERSION
    requires: ClassVar[tuple[str, ...]] = ("analyze", "asr", "draft")
    weight: ClassVar[float] = 3.0
    cache_keep: ClassVar[int] = 12
    title_zh: ClassVar[str] = "對齊歌詞"
    title_en: ClassVar[str] = "Aligning lyrics"

    def is_needed(self, ctx: StageContext) -> bool:
        """Alignment needs lyrics."""
        return ctx.store.load().has_lyrics

    def _only_lines(self, ctx: StageContext) -> list[str] | None:
        value = ctx.options.get("align_only_lines")
        return [str(item) for item in value] if value else None

    def inputs(self, ctx: StageContext) -> StageInputs:
        """Vocal stem, features, transcript, the lyrics with locked anchors, and parameters."""
        project = ctx.store.load()
        settings = ctx.profile.align
        aligner = create_aligner(settings, ctx.profile.asr, resolve_device(ctx.profile.device))
        return StageInputs(
            files={
                "vocals": ctx.paths.media / "vocals.wav",
                "features": ctx.output_of("analyze") / FEATURES_FILE,
                "transcript": ctx.output_of("asr") / TRANSCRIPT_FILE,
            },
            params=settings.model_dump() | {"model": aligner_model(settings, ctx.profile.asr)},
            adapters={"aligner": aligner.info.tag},
            data=alignment_fingerprint(project, self._only_lines(ctx)),
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Run coarse, fine and refinement passes."""
        project = ctx.store.load()
        settings = ctx.profile.align
        aligner = create_aligner(settings, ctx.profile.asr, resolve_device(ctx.profile.device))
        lines = lyric_lines(project)
        only = self._only_lines(ctx)
        if not aligner.info.supports_language(project.meta.language):
            raise AlignmentError(
                f"對齊器「{aligner.info.name}」不支援語言 {project.meta.language}。",
                f"Aligner '{aligner.info.name}' does not support language {project.meta.language}.",
                hint_zh="請換一個對齊器,例如 align.aligner=whisper-attn。",
                hint_en="Choose another aligner, e.g. align.aligner=whisper-attn.",
            )
        audio = read_mono(ctx.paths.media / "vocals.wav")
        features = load_features(ctx.output_of("analyze") / FEATURES_FILE)
        transcript = load_transcript(ctx.output_of("asr") / TRANSCRIPT_FILE)
        output = run_alignment(
            lines,
            audio=audio,
            features=features,
            words=transcript.words,
            aligner=aligner,
            settings=settings,
            language=project.meta.language,
            progress=ctx.progress,
            cancel=ctx.cancel,
            max_window_s=getattr(aligner, "max_window_s", None),
        )
        text_by_id = {line.id: [token.text for token in line.tokens] for line in project.lines}
        entries: list[dict[str, Any]] = []
        for line, tokens, confidences, window in zip(
            lines, output.tokens, output.confidences, output.windows, strict=True
        ):
            entries.append(
                {
                    "id": line.id,
                    "window": {
                        "start_ms": round(window.start_s * 1000),
                        "end_ms": round(window.end_s * 1000),
                        "quality": round(window.quality, 3),
                        "source": window.source,
                    },
                    "tokens": [
                        {
                            "text": text,
                            "start_ms": round(token.start_s * 1000),
                            "end_ms": round(token.end_s * 1000),
                            "confidence": confidence,
                            "score": round(token.score, 3),
                            "raw_start_ms": round(token.raw_start_s * 1000),
                            "snapped": token.snapped,
                            "locked": token.locked,
                        }
                        for text, token, confidence in zip(
                            text_by_id[line.id], tokens, confidences, strict=True
                        )
                    ],
                }
            )
        (out_dir / ALIGNMENT_FILE).write_text(
            json.dumps({"lines": entries}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        flat = [value for line in output.confidences for value in line]
        return {
            "aligner": aligner.info.tag,
            "lines": len(entries),
            "tokens": len(flat),
            "only_lines": only,
            "mean_confidence": round(sum(flat) / len(flat), 3) if flat else None,
            "low_confidence_tokens": sum(1 for value in flat if value < 0.5),
            "windows_from": {
                source: sum(1 for window in output.windows if window.source == source)
                for source in ("asr", "anchor", "hint", "regions", "interpolated")
            },
            "seconds": {key: round(value, 3) for key, value in output.seconds.items()},
        }

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Merge the aligned times into the project (locked tokens stay untouched)."""
        alignment = json.loads((out_dir / ALIGNMENT_FILE).read_text(encoding="utf-8"))
        only = self._only_lines(ctx)
        update_project(ctx, lambda project: _apply(project, alignment, only))


def _apply(project: Project, alignment: dict[str, Any], only: list[str] | None) -> None:
    apply_alignment(project, alignment, only)
