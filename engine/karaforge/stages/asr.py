"""Stage: speech recognition on the vocal stem (word timestamps).

The transcript serves two purposes: the coarse alignment pass matches it against the lyrics,
and when a project has no lyrics it becomes the lyric draft.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from karaforge.adapters.base import AsrSegment, AsrWord, Transcript
from karaforge.adapters.registry import create_transcriber
from karaforge.audio.io import read_mono
from karaforge.device import resolve_device
from karaforge.pipeline.stage import JsonDict, Stage, StageContext, StageInputs
from karaforge.project.schema import Project

TRANSCRIPT_FILE = "transcript.json"
_PROMPT_MAX_CHARS = 400


def lyrics_prompt(project: Project) -> str | None:
    """Text used to bias recognition towards the known lyrics: each distinct line once.

    A draft that came out of the recogniser tells it nothing new, so a project whose lyrics
    are such a draft has no prompt — exactly as when it had no lyrics at all.  That keeps
    the transcript (and everything computed from it) valid while the draft is corrected.
    """
    if project.meta.lyrics_source == "asr":
        return None
    seen: set[str] = set()
    parts: list[str] = []
    for line in project.lines:
        text = line.text.strip()
        if text and text not in seen:
            seen.add(text)
            parts.append(text)
    joined = " ".join(parts)
    return joined[:_PROMPT_MAX_CHARS] or None


def transcript_to_json(transcript: Transcript) -> dict[str, Any]:
    """Serialise a transcript."""
    return {
        "language": transcript.language,
        "segments": [
            {
                "text": segment.text,
                "start_s": segment.start_s,
                "end_s": segment.end_s,
                "words": [
                    {
                        "text": word.text,
                        "start_s": word.start_s,
                        "end_s": word.end_s,
                        "probability": word.probability,
                    }
                    for word in segment.words
                ],
            }
            for segment in transcript.segments
        ],
    }


def transcript_from_json(data: dict[str, Any]) -> Transcript:
    """Rebuild a transcript written by :func:`transcript_to_json`."""
    return Transcript(
        language=str(data.get("language", "")),
        segments=tuple(
            AsrSegment(
                text=str(segment["text"]),
                start_s=float(segment["start_s"]),
                end_s=float(segment["end_s"]),
                words=tuple(
                    AsrWord(
                        text=str(word["text"]),
                        start_s=float(word["start_s"]),
                        end_s=float(word["end_s"]),
                        probability=float(word.get("probability", 1.0)),
                    )
                    for word in segment.get("words", [])
                ),
            )
            for segment in data.get("segments", [])
        ),
    )


def load_transcript(path: Path) -> Transcript:
    """Read ``transcript.json``."""
    return transcript_from_json(json.loads(path.read_text(encoding="utf-8")))


class AsrStage(Stage):
    """Transcribe ``vocals.wav`` with the configured recogniser."""

    name: ClassVar[str] = "asr"
    version: ClassVar[str] = "1"
    requires: ClassVar[tuple[str, ...]] = ("separate",)
    weight: ClassVar[float] = 2.0
    title_zh: ClassVar[str] = "語音辨識"
    title_en: ClassVar[str] = "Speech recognition"

    def _prompt(self, ctx: StageContext, project: Project) -> str | None:
        return lyrics_prompt(project) if ctx.profile.asr.use_lyrics_prompt else None

    def inputs(self, ctx: StageContext) -> StageInputs:
        """The vocal stem, the recogniser and the prompt derived from the lyrics."""
        project = ctx.store.load()
        transcriber = create_transcriber(ctx.profile.asr, resolve_device(ctx.profile.device))
        prompt = self._prompt(ctx, project)
        params: JsonDict = {"beam_size": ctx.profile.asr.beam_size}
        if prompt is None:
            # Recognition without a prompt changed (the "no speech" gate is off, see the
            # adapter).  Only those runs get a new cache key; transcripts made with a prompt
            # are what they always were and stay valid.
            params["no_speech_gate"] = False
        return StageInputs(
            files={"vocals": ctx.paths.media / "vocals.wav"},
            params=params,
            adapters={"asr": transcriber.info.tag},
            data={"language": project.meta.language, "prompt": prompt},
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Run recognition and store the transcript."""
        project = ctx.store.load()
        transcriber = create_transcriber(ctx.profile.asr, resolve_device(ctx.profile.device))
        audio = read_mono(ctx.paths.media / "vocals.wav")
        transcript = transcriber.transcribe(
            audio,
            language=project.meta.language,
            prompt=self._prompt(ctx, project),
            progress=ctx.progress,
            cancel=ctx.cancel,
        )
        (out_dir / TRANSCRIPT_FILE).write_text(
            json.dumps(transcript_to_json(transcript), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        return {
            "asr": transcriber.info.tag,
            "language": transcript.language,
            "segments": len(transcript.segments),
            "words": len(transcript.words),
        }

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Nothing to publish: downstream stages read the transcript from the cache folder."""
