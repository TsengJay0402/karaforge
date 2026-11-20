"""Stages ⑤ layout and ⑥ ass: build the render plan and the ASS script."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from karaforge.ass.writer import ASS_WRITER_VERSION, render_ass
from karaforge.errors import PipelineError
from karaforge.layout.engine import LAYOUT_VERSION, build_plan
from karaforge.layout.fonts import default_library
from karaforge.layout.plan import RenderPlan
from karaforge.layout.theme import load_theme
from karaforge.pipeline.stage import JsonDict, Stage, StageContext, StageInputs
from karaforge.project.schema import Project

ASS_FILE = "subtitles.ass"
PLAN_FILE = "plan.json"


def require_aligned(project: Project) -> None:
    """Raise a helpful error when the project has nothing that can be drawn.

    Raises:
        PipelineError: If there are no lyrics or no token has been aligned.
    """
    if not project.has_lyrics:
        raise PipelineError(
            "這個專案還沒有歌詞。",
            "This project has no lyrics yet.",
            hint_zh="請加入歌詞,或執行 `kf run` 讓語音辨識產生草稿。",
            hint_en="Add lyrics, or run `kf run` to draft them with speech recognition.",
        )
    if not any(token.is_timed for line in project.lines for token in line.tokens):
        raise PipelineError(
            "歌詞還沒有對齊到音樂。",
            "The lyrics have not been aligned to the audio yet.",
            hint_zh="請先執行 `kf run <專案>`。",
            hint_en="Run `kf run <project>` first.",
        )


class SubtitlesStage(Stage):
    """Lay out the lyrics and write ``subtitles.ass`` plus the render plan as JSON."""

    name: ClassVar[str] = "subtitles"
    version: ClassVar[str] = f"{LAYOUT_VERSION}.{ASS_WRITER_VERSION}"
    requires: ClassVar[tuple[str, ...]] = ("align",)
    weight: ClassVar[float] = 0.2
    cache_keep: ClassVar[int] = 6
    title_zh: ClassVar[str] = "排版字幕"
    title_en: ClassVar[str] = "Laying out subtitles"

    def inputs(self, ctx: StageContext) -> StageInputs:
        """The document parts that affect the picture, the theme and the font files."""
        project = ctx.store.load()
        theme = load_theme(project.style.theme).with_overrides(project.style.overrides)
        library = default_library()
        fonts = {
            f"font:{face.family}": face.path
            for face in library.faces
            if face.family in (theme.font.family, theme.font.fallback)
            or theme.font.family.lower() in face.aliases
            or theme.font.fallback.lower() in face.aliases
        }
        return StageInputs(
            files=fonts,
            data={
                "meta": project.meta.model_dump(),
                "singers": [singer.model_dump() for singer in project.singers],
                "lines": [line.model_dump() for line in project.lines],
                "render": project.render.model_dump(),
                "analysis": {
                    "tempo_bpm": project.analysis.tempo_bpm,
                    "beats_ms": project.analysis.beats_ms,
                },
                "theme": theme.model_dump(),
            },
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        """Build the plan and the script."""
        project = ctx.store.load()
        require_aligned(project)
        plan = build_plan(project)
        (out_dir / PLAN_FILE).write_text(plan.model_dump_json(indent=1), encoding="utf-8")
        (out_dir / ASS_FILE).write_text(
            render_ass(plan, title=project.meta.title), encoding="utf-8"
        )
        return {
            "lines": len(plan.lines),
            "countdowns": len(plan.countdowns),
            "title_card": plan.title_card is not None,
            "fonts": [font.family for font in plan.fonts],
        }

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        """Nothing to publish: the export stage reads the files from the cache folder."""


def load_plan(path: Path) -> RenderPlan:
    """Read a render plan written by :class:`SubtitlesStage`."""
    return RenderPlan.model_validate_json(path.read_text(encoding="utf-8"))
