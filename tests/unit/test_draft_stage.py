"""The "no lyrics" flow at pipeline level, with stand-ins for the model stages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from karaforge.adapters.base import AsrSegment, AsrWord, Transcript
from karaforge.pipeline import PipelineRunner, Stage, StageContext, StageInputs, get_profile
from karaforge.pipeline.stage import JsonDict, update_project
from karaforge.project import Project, ProjectStore
from karaforge.project.schema import Line, Token
from karaforge.stages.asr import TRANSCRIPT_FILE, lyrics_prompt, transcript_to_json
from karaforge.stages.draft import DRAFT_FILE, DraftStage


def phrase(start_s: float, text: str, step_s: float = 0.3) -> AsrSegment:
    """A recognised phrase: one word per character, back to back."""
    words = tuple(
        AsrWord(char, start_s + index * step_s, start_s + (index + 1) * step_s, 0.8)
        for index, char in enumerate(text)
    )
    return AsrSegment(text, words[0].start_s, words[-1].end_s, words)


TRANSCRIPT = Transcript(
    "zh",
    (
        phrase(0.5, "请订阅我的频道"),  # recognised in the intro, where nobody sings
        phrase(10.0, "车窗上的雨滴"),
        phrase(13.0, "排成一条线"),
        phrase(30.0, "山谷里传来回音"),
    ),
)


class FakeAnalyze(Stage):
    """Publishes voice-activity regions like the real analysis does."""

    name: ClassVar[str] = "analyze"

    def inputs(self, ctx: StageContext) -> StageInputs:
        return StageInputs()

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        return {"vocal_regions": [[9800, 15000], [29500, 33000]]}

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        def apply(project: Project) -> None:
            project.analysis.vocal_regions = [(9800, 15000), (29500, 33000)]

        update_project(ctx, apply)


class FakeAsr(Stage):
    """Writes a fixed transcript; its cache key depends on the prompt like the real stage."""

    name: ClassVar[str] = "asr"
    runs: ClassVar[list[str | None]] = []

    def inputs(self, ctx: StageContext) -> StageInputs:
        return StageInputs(data={"prompt": lyrics_prompt(ctx.store.load())})

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        FakeAsr.runs.append(lyrics_prompt(ctx.store.load()))
        (out_dir / TRANSCRIPT_FILE).write_text(
            json.dumps(transcript_to_json(TRANSCRIPT), ensure_ascii=False), encoding="utf-8"
        )
        return {}

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        return None


class FakeAlign(Stage):
    """Remembers the lyrics it was asked to align."""

    name: ClassVar[str] = "align"
    requires: ClassVar[tuple[str, ...]] = ("analyze", "asr", "draft")
    seen: ClassVar[list[list[str]]] = []

    def is_needed(self, ctx: StageContext) -> bool:
        return ctx.store.load().has_lyrics

    def inputs(self, ctx: StageContext) -> StageInputs:
        return StageInputs(data={"text": [line.text for line in ctx.store.load().lines]})

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        FakeAlign.seen.append([line.text for line in ctx.store.load().lines])
        return {}

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        return None


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    FakeAsr.runs.clear()
    FakeAlign.seen.clear()
    project_store = ProjectStore(tmp_path / "song.kfproj")
    project_store.create(Project())
    return project_store


def run(store: ProjectStore) -> dict[str, str]:
    runner = PipelineRunner([FakeAnalyze(), FakeAsr(), DraftStage(), FakeAlign()])
    context = StageContext(store=store, profile=get_profile("cpu-lite"))
    report = runner.run(context, targets=["align"])
    return {stage.stage: stage.status for stage in report.stages}


def test_a_project_without_lyrics_gets_a_draft_and_is_aligned(store: ProjectStore) -> None:
    statuses = run(store)
    assert statuses == {
        "analyze": "finished",
        "asr": "finished",
        "draft": "finished",
        "align": "finished",
    }
    project = store.load()
    # Traditional script, one line per phrase, nothing from the silent intro.
    assert [line.text for line in project.lines] == ["車窗上的雨滴", "排成一條線", "山谷裡傳來回音"]
    assert project.meta.lyrics_source == "asr"
    assert [line.paragraph for line in project.lines] == [0, 0, 1]
    assert project.lines[0].time_hint == (10000, 11800)
    first = project.lines[0].tokens[0]
    assert (first.text, first.start_ms, first.end_ms) == ("車", 10000, 10300)
    assert (first.confidence, first.locked, first.source) == (0.8, False, "auto")
    assert project.is_aligned
    # The alignment ran on the draft, in the same run.
    assert FakeAlign.seen == [["車窗上的雨滴", "排成一條線", "山谷裡傳來回音"]]


def test_the_draft_is_made_once_and_survives_corrections(store: ProjectStore) -> None:
    run(store)
    project = store.load()
    project.lines[1] = Line(id="L002", tokens=[Token(text=char) for char in "排成了一條線"])
    store.save(project)

    statuses = run(store)
    # No lyrics prompt for a draft: the transcript stays valid, recognition is not repeated.
    assert FakeAsr.runs == [None]
    assert statuses["asr"] == "cached"
    assert statuses["draft"] == "skipped"
    assert statuses["align"] == "finished"
    after = store.load()
    assert after.lines[1].text == "排成了一條線"
    assert after.meta.lyrics_source == "asr"
    assert FakeAlign.seen[-1][1] == "排成了一條線"


def test_typed_lyrics_are_never_replaced_by_a_draft(store: ProjectStore) -> None:
    project = store.load()
    project.lines = [Line(id="L001", tokens=[Token(text=char) for char in "自己打的歌詞"])]
    store.save(project)
    statuses = run(store)
    assert statuses["draft"] == "skipped"
    after = store.load()
    assert [line.text for line in after.lines] == ["自己打的歌詞"]
    assert after.meta.lyrics_source == "user"
    # Lyrics given by the user do bias the recogniser.
    assert FakeAsr.runs == ["自己打的歌詞"]


def test_publish_does_not_overwrite_lyrics_that_appeared_meanwhile(
    store: ProjectStore, tmp_path: Path
) -> None:
    asr_dir = tmp_path / "asr-output"
    asr_dir.mkdir()
    (asr_dir / TRANSCRIPT_FILE).write_text(
        json.dumps(transcript_to_json(TRANSCRIPT), ensure_ascii=False), encoding="utf-8"
    )
    context = StageContext(store=store, profile=get_profile("cpu-lite"))
    context.outputs["asr"] = asr_dir
    stage = DraftStage()
    assert stage.is_needed(context)
    out_dir = tmp_path / "draft-output"
    out_dir.mkdir()
    result = stage.run(context, out_dir)
    # Without voice-activity regions nothing is filtered: the intro phrase is kept.
    assert result == {"lines": 4, "tokens": 25, "recognised_words": 25, "language": "zh"}
    assert len(json.loads((out_dir / DRAFT_FILE).read_text(encoding="utf-8"))["lines"]) == 4

    # While the stage was running, the user pasted lyrics in the editor.
    project = store.load()
    project.lines = [Line(id="L001", tokens=[Token(text="啦")])]
    store.save(project)
    revision = store.current_revision()
    stage.publish(context, out_dir, result)
    assert [line.text for line in store.load().lines] == ["啦"]
    assert store.current_revision() == revision
    assert not stage.is_needed(context)


def test_nothing_recognised_leaves_the_project_without_lyrics(
    store: ProjectStore, tmp_path: Path
) -> None:
    asr_dir = tmp_path / "asr-output"
    asr_dir.mkdir()
    (asr_dir / TRANSCRIPT_FILE).write_text(
        json.dumps(transcript_to_json(Transcript("zh", ()))), encoding="utf-8"
    )
    context = StageContext(store=store, profile=get_profile("cpu-lite"))
    context.outputs["asr"] = asr_dir
    stage = DraftStage()
    out_dir = tmp_path / "draft-output"
    out_dir.mkdir()
    result = stage.run(context, out_dir)
    assert result["lines"] == 0
    stage.publish(context, out_dir, result)
    after = store.load()
    assert not after.has_lyrics and after.meta.lyrics_source == "user"
