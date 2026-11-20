"""Stage: draft the lyrics from the transcript when the project has none.

This is the "no lyrics" flow: speech recognition → draft → (proofreading by the user) →
alignment.  The stage only applies while the project has no lyrics; once a draft has been
written — or the user has typed lyrics in — it is skipped and never overwrites anything.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, ClassVar

from karaforge.align.draft import DraftSettings, draft_lyrics, to_project_lines
from karaforge.pipeline.stage import JsonDict, Stage, StageContext, StageInputs, update_project
from karaforge.project.schema import Line, Project
from karaforge.stages.asr import TRANSCRIPT_FILE, load_transcript
from karaforge.text.ruby import annotate_project

DRAFT_FILE = "draft.json"


def _regions(project: Project) -> list[tuple[float, float]]:
    return [(start / 1000.0, end / 1000.0) for start, end in project.analysis.vocal_regions]


class DraftStage(Stage):
    """Turn the transcript into lyric lines for a project without lyrics."""

    name: ClassVar[str] = "draft"
    version: ClassVar[str] = "1"
    requires: ClassVar[tuple[str, ...]] = ("analyze", "asr")
    weight: ClassVar[float] = 0.05
    title_zh: ClassVar[str] = "產生歌詞草稿"
    title_en: ClassVar[str] = "Drafting lyrics"

    def is_needed(self, ctx: StageContext) -> bool:
        """Only a project without lyrics gets a draft."""
        return not ctx.store.load().has_lyrics

    def inputs(self, ctx: StageContext) -> StageInputs:
        """The transcript, where somebody sings, the language and the line-cutting rules."""
        project = ctx.store.load()
        return StageInputs(
            files={"transcript": ctx.output_of("asr") / TRANSCRIPT_FILE},
            params=asdict(DraftSettings()),
            data={
                "language": project.meta.language,
                "vocal_regions": [list(pair) for pair in project.analysis.vocal_regions],
            },
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Build the draft and store it."""
        project = ctx.store.load()
        transcript = load_transcript(ctx.output_of("asr") / TRANSCRIPT_FILE)
        draft = draft_lyrics(transcript, project.meta.language, _regions(project))
        lines = to_project_lines(draft)
        (out_dir / DRAFT_FILE).write_text(
            json.dumps(
                {"lines": [line.model_dump(mode="json") for line in lines]},
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        recognised = sum(len(segment.words) for segment in transcript.segments)
        tokens = sum(len(line.tokens) for line in lines)
        if recognised and not tokens:
            ctx.progress(1.0, "辨識結果裡沒有可用的歌詞 / nothing usable was recognised")
        return {
            "lines": len(lines),
            "tokens": tokens,
            "recognised_words": recognised,
            "language": transcript.language,
        }

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Write the draft into the project — unless lyrics have appeared in the meantime."""
        data: dict[str, Any] = json.loads((out_dir / DRAFT_FILE).read_text(encoding="utf-8"))
        lines = [Line.model_validate(item) for item in data.get("lines", [])]

        def apply(project: Project) -> None:
            if project.has_lyrics or not lines:
                return
            project.lines = lines
            project.meta.lyrics_source = "asr"
            annotate_project(project)

        update_project(ctx, apply)
