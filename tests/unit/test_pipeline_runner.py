from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from karaforge.errors import JobCancelledError, MediaError, PipelineError
from karaforge.pipeline import (
    PipelineRunner,
    Stage,
    StageContext,
    StageEvent,
    StageInputs,
    get_profile,
)
from karaforge.pipeline.stage import JsonDict, link_or_copy
from karaforge.project import Project, ProjectStore
from karaforge.runtime import CancelToken


class Recorder:
    """Counts what the test stages do."""

    def __init__(self) -> None:
        self.runs: list[str] = []
        self.publishes: list[str] = []


class SourceStage(Stage):
    """Writes ``options["text"]`` (upper-cased when ``options["upper"]``) to a file."""

    name: ClassVar[str] = "source"
    version: ClassVar[str] = "1"

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    def inputs(self, ctx: StageContext) -> StageInputs:
        return StageInputs(
            params={"text": ctx.options.get("text", "hello"), "salt": ctx.options.get("salt", 0)}
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        self.recorder.runs.append(self.name)
        (out_dir / "text.txt").write_text(str(ctx.options.get("text", "hello")), encoding="utf-8")
        ctx.progress(1.0, "done")
        return {"length": len(str(ctx.options.get("text", "hello")))}

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        self.recorder.publishes.append(self.name)
        link_or_copy(out_dir / "text.txt", ctx.paths.media / "text.txt")


class UpperStage(Stage):
    """Upper-cases the published text; depends on the *content* of ``source``'s output."""

    name: ClassVar[str] = "upper"
    requires: ClassVar[tuple[str, ...]] = ("source",)

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    def inputs(self, ctx: StageContext) -> StageInputs:
        return StageInputs(
            files={"text": ctx.paths.media / "text.txt"},
            params={"suffix": ctx.options.get("suffix", "")},
        )

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        self.recorder.runs.append(self.name)
        text = (ctx.paths.media / "text.txt").read_text(encoding="utf-8")
        (out_dir / "upper.txt").write_text(text.upper() + str(ctx.options.get("suffix", "")))
        return {"source_dir": str(ctx.output_of("source"))}

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        self.recorder.publishes.append(self.name)
        link_or_copy(out_dir / "upper.txt", ctx.paths.media / "upper.txt")


class CountStage(Stage):
    """Counts characters of the upper-cased text."""

    name: ClassVar[str] = "count"
    requires: ClassVar[tuple[str, ...]] = ("upper",)

    def __init__(self, recorder: Recorder, needed: bool = True) -> None:
        self.recorder = recorder
        self.needed = needed

    def is_needed(self, ctx: StageContext) -> bool:
        return self.needed

    def inputs(self, ctx: StageContext) -> StageInputs:
        return StageInputs(files={"upper": ctx.paths.media / "upper.txt"})

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        self.recorder.runs.append(self.name)
        return {"count": len((ctx.paths.media / "upper.txt").read_text())}

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        self.recorder.publishes.append(self.name)


class FailingStage(Stage):
    name: ClassVar[str] = "failing"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def inputs(self, ctx: StageContext) -> StageInputs:
        return StageInputs()

    def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
        (out_dir / "half-written.bin").write_bytes(b"x")
        raise self.error

    def publish(self, ctx: StageContext, out_dir: Path, result: JsonDict) -> None:
        raise AssertionError("must not be published")


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    project_store = ProjectStore(tmp_path / "song.kfproj")
    project_store.create(Project())
    return project_store


def make(store: ProjectStore, **options: object) -> StageContext:
    return StageContext(store=store, profile=get_profile("cpu-lite"), options=dict(options))


def pipeline(recorder: Recorder) -> PipelineRunner:
    return PipelineRunner([CountStage(recorder), UpperStage(recorder), SourceStage(recorder)])


def test_stages_run_in_dependency_order_whatever_the_registration_order(
    store: ProjectStore,
) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    assert runner.stage_names == ["source", "upper", "count"]
    report = runner.run(make(store))
    assert recorder.runs == ["source", "upper", "count"]
    assert report.executed == ["source", "upper", "count"]
    assert report["count"].result == {"count": 5}
    assert (store.paths.media / "upper.txt").read_text() == "HELLO"


def test_second_run_is_served_from_cache_but_still_published(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    runner.run(make(store))
    (store.paths.media / "upper.txt").unlink()
    report = runner.run(make(store))
    assert recorder.runs == ["source", "upper", "count"]
    assert report.cached == ["source", "upper", "count"]
    assert report.executed == []
    assert recorder.publishes.count("upper") == 2
    assert (store.paths.media / "upper.txt").read_text() == "HELLO"
    assert report["count"].result == {"count": 5}
    assert report["count"].cached


def test_changed_parameter_reruns_only_what_depends_on_it(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    runner.run(make(store))
    recorder.runs.clear()
    report = runner.run(make(store, suffix="!!"))
    assert recorder.runs == ["upper", "count"]
    assert report.cached == ["source"]
    assert report["count"].result == {"count": 7}


def test_unchanged_output_stops_the_rerun_from_spreading(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    runner.run(make(store))
    recorder.runs.clear()
    # ``salt`` changes the key of ``source`` but not the bytes it writes.
    report = runner.run(make(store, salt=1))
    assert recorder.runs == ["source"]
    assert report.cached == ["upper", "count"]


def test_force_from_reruns_the_stage_and_everything_downstream(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    runner.run(make(store))
    recorder.runs.clear()
    report = runner.run(make(store), force_from="upper")
    assert recorder.runs == ["upper", "count"]
    assert report.cached == ["source"]
    assert runner.downstream("source") == {"source", "upper", "count"}
    with pytest.raises(PipelineError):
        runner.run(make(store), force_from="nope")


def test_targets_pull_in_their_dependencies(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    report = runner.run(make(store), targets=["upper"])
    assert recorder.runs == ["source", "upper"]
    assert "count" not in report
    assert runner.closure(["count"]) == ["source", "upper", "count"]


def test_targets_without_dependencies_run_exactly_those_stages(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    runner.run(make(store))
    recorder.runs.clear()
    # The published text changes behind the pipeline's back (like an edit in the editor).
    (store.paths.media / "upper.txt").unlink()
    (store.paths.media / "upper.txt").write_text("EDITED BY HAND")
    report = runner.run(make(store, text="other"), targets=["count"], include_dependencies=False)
    assert recorder.runs == ["count"]
    assert [stage.stage for stage in report.stages] == ["count"]
    assert report["count"].result == {"count": 14}


def test_stage_that_is_not_needed_is_skipped(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = PipelineRunner(
        [SourceStage(recorder), UpperStage(recorder), CountStage(recorder, needed=False)]
    )
    events: list[StageEvent] = []
    report = runner.run(make(store), on_event=events.append)
    assert recorder.runs == ["source", "upper"]
    assert report["count"].status == "skipped"
    assert events[-1] == StageEvent("count", "skipped")


def test_events_and_progress(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    events: list[StageEvent] = []
    fractions: list[float] = []
    context = StageContext(
        store=store,
        profile=get_profile("cpu-lite"),
        progress=lambda fraction, _message: fractions.append(fraction),
    )
    runner.run(context, on_event=events.append)
    assert [(event.stage, event.status) for event in events] == [
        ("source", "started"),
        ("source", "finished"),
        ("upper", "started"),
        ("upper", "finished"),
        ("count", "started"),
        ("count", "finished"),
    ]
    assert all(event.key and len(event.key) == 64 for event in events)
    assert fractions == sorted(fractions)
    assert fractions[-1] == pytest.approx(1.0)

    events.clear()
    runner.run(context, on_event=events.append)
    assert [event.status for event in events] == ["cached", "cached", "cached"]


def test_cancellation_stops_before_the_next_stage(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = pipeline(recorder)
    token = CancelToken()
    token.cancel()
    context = StageContext(store=store, profile=get_profile("cpu-lite"), cancel=token)
    with pytest.raises(JobCancelledError):
        runner.run(context)
    assert recorder.runs == []


def test_cancellation_during_a_stage_discards_its_output(store: ProjectStore) -> None:
    token = CancelToken()

    class CancelsItself(SourceStage):
        def run(self, ctx: StageContext, out_dir: Path) -> JsonDict:
            result = super().run(ctx, out_dir)
            token.cancel()
            return result

    recorder = Recorder()
    runner = PipelineRunner([CancelsItself(recorder)])
    context = StageContext(store=store, profile=get_profile("cpu-lite"), cancel=token)
    with pytest.raises(JobCancelledError):
        runner.run(context)
    assert recorder.publishes == []
    assert list((store.paths.cache / "source").iterdir()) == []


def test_unexpected_exception_is_wrapped_and_partial_output_removed(store: ProjectStore) -> None:
    runner = PipelineRunner([FailingStage(ZeroDivisionError("boom"))])
    with pytest.raises(PipelineError) as info:
        runner.run(make(store))
    assert info.value.detail == "ZeroDivisionError: boom"
    assert "failing" in info.value.message_en
    assert list((store.paths.cache / "failing").iterdir()) == []


def test_karaforge_errors_pass_through_unchanged(store: ProjectStore) -> None:
    error = MediaError("壞掉的檔案", "broken file")
    runner = PipelineRunner([FailingStage(error)])
    with pytest.raises(MediaError) as info:
        runner.run(make(store))
    assert info.value is error


def test_missing_input_file_is_reported(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = PipelineRunner([SourceStage(recorder), UpperStage(recorder)])
    with pytest.raises(PipelineError) as info:
        runner.run(make(store), targets=["upper"], include_dependencies=False)
    assert "text.txt" in (info.value.detail or "")


def test_reading_an_undeclared_upstream_output_is_an_error(store: ProjectStore) -> None:
    context = make(store)
    with pytest.raises(PipelineError):
        context.output_of("source")


def test_invalid_graphs_are_rejected() -> None:
    recorder = Recorder()
    with pytest.raises(ValueError, match="duplicate"):
        PipelineRunner([SourceStage(recorder), SourceStage(recorder)])
    with pytest.raises(ValueError, match="unknown stage"):
        PipelineRunner([UpperStage(recorder)])

    class A(SourceStage):
        name: ClassVar[str] = "a"
        requires: ClassVar[tuple[str, ...]] = ("b",)

    class B(SourceStage):
        name: ClassVar[str] = "b"
        requires: ClassVar[tuple[str, ...]] = ("a",)

    with pytest.raises(ValueError, match="cycle"):
        PipelineRunner([A(recorder), B(recorder)])


def test_old_cache_entries_are_pruned(store: ProjectStore) -> None:
    class KeepTwo(SourceStage):
        cache_keep: ClassVar[int] = 2

    recorder = Recorder()
    runner = PipelineRunner([KeepTwo(recorder)])
    for index in range(5):
        runner.run(make(store, text=f"text {index}"))
    entries = [path for path in (store.paths.cache / "source").iterdir() if path.is_dir()]
    assert len(entries) == 2
    kept = sorted((entry / "text.txt").read_text() for entry in entries)
    assert "text 4" in kept


def test_corrupt_cache_entry_is_recomputed(store: ProjectStore) -> None:
    recorder = Recorder()
    runner = PipelineRunner([SourceStage(recorder)])
    report = runner.run(make(store))
    key = report["source"].key
    assert key is not None
    (store.paths.cache / "source" / key / "result.json").write_text("{broken", encoding="utf-8")
    again = runner.run(make(store))
    assert again.executed == ["source"]
    assert json.loads((store.paths.cache / "source" / key / "result.json").read_text()) == {
        "length": 5
    }
