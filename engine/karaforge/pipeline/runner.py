"""Runs stages in dependency order with content-hash caching, progress and cancellation."""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeVar

from karaforge.errors import JobCancelledError, KaraForgeError, PipelineError
from karaforge.pipeline.hashing import sha256_json
from karaforge.pipeline.stage import JsonDict, Stage, StageContext
from karaforge.runtime import subprogress

RESULT_FILE = "result.json"
StageStatus = Literal["started", "cached", "finished", "skipped"]
_T = TypeVar("_T")


@dataclass(frozen=True)
class StageEvent:
    """Notification emitted by the runner as stages start and end."""

    stage: str
    status: StageStatus
    key: str | None = None
    seconds: float = 0.0


@dataclass
class StageReport:
    """Outcome of one stage in a run."""

    stage: str
    status: StageStatus
    key: str | None = None
    seconds: float = 0.0
    result: JsonDict = field(default_factory=dict[str, object])

    @property
    def cached(self) -> bool:
        """Whether the stage's output came from the cache."""
        return self.status == "cached"


@dataclass
class RunReport:
    """Outcome of a pipeline run."""

    stages: list[StageReport] = field(default_factory=list[StageReport])

    def __getitem__(self, stage: str) -> StageReport:
        for report in self.stages:
            if report.stage == stage:
                return report
        raise KeyError(stage)

    def __contains__(self, stage: str) -> bool:
        return any(report.stage == stage for report in self.stages)

    @property
    def executed(self) -> list[str]:
        """Names of the stages that actually ran (cache misses)."""
        return [report.stage for report in self.stages if report.status == "finished"]

    @property
    def cached(self) -> list[str]:
        """Names of the stages that were served from the cache."""
        return [report.stage for report in self.stages if report.status == "cached"]


EventFn = Callable[[StageEvent], None]


def _ignore_event(event: StageEvent) -> None:
    """Default event sink."""


class PipelineRunner:
    """Executes a set of stages as a dependency graph.

    Args:
        stages: All stages that may run.  Their ``requires`` attributes define the graph.
    """

    def __init__(self, stages: Iterable[Stage]) -> None:
        self._stages: dict[str, Stage] = {}
        for stage in stages:
            if stage.name in self._stages:
                raise ValueError(f"duplicate stage name: {stage.name}")
            self._stages[stage.name] = stage
        for stage in self._stages.values():
            for dependency in stage.requires:
                if dependency not in self._stages:
                    raise ValueError(f"stage {stage.name} requires unknown stage {dependency}")
        self._order = self._topological_order()

    @property
    def stage_names(self) -> list[str]:
        """All stage names in execution order."""
        return list(self._order)

    def stage(self, name: str) -> Stage:
        """Look up a stage by name."""
        try:
            return self._stages[name]
        except KeyError:
            raise PipelineError(
                f"沒有這個處理階段:{name}",
                f"Unknown stage: {name}",
                hint_zh=f"可用的階段:{'、'.join(self._order)}",
                hint_en=f"Available stages: {', '.join(self._order)}",
            ) from None

    def _topological_order(self) -> list[str]:
        order: list[str] = []
        state: dict[str, int] = {}

        def visit(name: str, trail: tuple[str, ...]) -> None:
            if state.get(name) == 2:
                return
            if state.get(name) == 1:
                raise ValueError("dependency cycle: " + " -> ".join((*trail, name)))
            state[name] = 1
            for dependency in self._stages[name].requires:
                visit(dependency, (*trail, name))
            state[name] = 2
            order.append(name)

        for name in self._stages:
            visit(name, ())
        return order

    def closure(self, targets: Sequence[str]) -> list[str]:
        """Return ``targets`` plus everything they depend on, in execution order."""
        needed: set[str] = set()

        def add(name: str) -> None:
            if name in needed:
                return
            needed.add(name)
            for dependency in self.stage(name).requires:
                add(dependency)

        for target in targets:
            add(target)
        return [name for name in self._order if name in needed]

    def downstream(self, name: str) -> set[str]:
        """Return ``name`` and every stage that (transitively) depends on it."""
        self.stage(name)
        affected = {name}
        changed = True
        while changed:
            changed = False
            for stage in self._stages.values():
                if stage.name not in affected and affected.intersection(stage.requires):
                    affected.add(stage.name)
                    changed = True
        return affected

    def cache_key(self, stage: Stage, ctx: StageContext) -> str:
        """Compute the cache key of ``stage`` for the project's current state."""
        declared = stage.inputs(ctx)
        missing = [str(path) for path in declared.files.values() if not path.is_file()]
        if missing:
            raise PipelineError(
                f"階段「{stage.name}」缺少輸入檔。",
                f"Stage '{stage.name}' is missing input files.",
                detail=", ".join(missing),
            )
        return sha256_json(
            {
                "stage": stage.name,
                "version": stage.version,
                "files": {name: ctx.hashes.digest(path) for name, path in declared.files.items()},
                "params": declared.params,
                "adapters": declared.adapters,
                "data": declared.data,
            }
        )

    def run(
        self,
        ctx: StageContext,
        *,
        targets: Sequence[str] | None = None,
        force_from: str | None = None,
        on_event: EventFn = _ignore_event,
        include_dependencies: bool = True,
    ) -> RunReport:
        """Run the pipeline.

        Args:
            ctx: Project, profile, progress callback and cancel token.
            targets: Stages to bring up to date (with their dependencies).  ``None`` means all.
            force_from: Re-run this stage and everything downstream even if cached.
            on_event: Receives a :class:`StageEvent` when a stage starts and when it ends.
            include_dependencies: When false, run exactly ``targets`` and nothing upstream.
                Used for exporting: an edited project must be rendered as it is, without the
                alignment being recomputed because the edits changed its inputs.

        Returns:
            What happened to each stage.

        Raises:
            JobCancelledError: If ``ctx.cancel`` was triggered.
            KaraForgeError: Whatever a stage raised (unexpected exceptions are wrapped in
                :class:`PipelineError`).
        """
        if targets is None:
            selected = list(self._order)
        elif include_dependencies:
            selected = self.closure(targets)
        else:
            wanted = {self.stage(name).name for name in targets}
            selected = [name for name in self._order if name in wanted]
        forced = self.downstream(force_from) if force_from else set[str]()
        total_weight = sum(self._stages[name].weight for name in selected) or 1.0
        report = RunReport()
        done_weight = 0.0

        for name in selected:
            stage = self._stages[name]
            ctx.cancel.raise_if_cancelled()
            start_fraction = done_weight / total_weight
            done_weight += stage.weight
            end_fraction = done_weight / total_weight
            stage_ctx = ctx.with_progress(subprogress(ctx.progress, start_fraction, end_fraction))

            if not stage.is_needed(stage_ctx):
                on_event(StageEvent(name, "skipped"))
                report.stages.append(StageReport(name, "skipped"))
                continue

            stage_report = self._run_stage(
                stage, stage_ctx, force=name in forced, on_event=on_event
            )
            report.stages.append(stage_report)
            if stage_report.key is not None:
                ctx.outputs[name] = ctx.paths.cache / name / stage_report.key
                ctx.results[name] = stage_report.result
            ctx.progress(end_fraction, "")
        return report

    def _run_stage(
        self, stage: Stage, ctx: StageContext, *, force: bool, on_event: EventFn
    ) -> StageReport:
        key = self.cache_key(stage, ctx)
        stage_dir = ctx.paths.cache / stage.name
        out_dir = stage_dir / key
        result_path = out_dir / RESULT_FILE
        started = time.monotonic()

        if result_path.is_file() and not force:
            result = _read_result(result_path)
            if result is not None:
                os.utime(out_dir)
                self._guarded(stage, lambda: stage.publish(ctx, out_dir, result))
                seconds = time.monotonic() - started
                on_event(StageEvent(stage.name, "cached", key, seconds))
                return StageReport(stage.name, "cached", key, seconds, result)

        on_event(StageEvent(stage.name, "started", key))
        partial = stage_dir / f"{key}.partial-{os.getpid()}"
        if partial.exists():
            shutil.rmtree(partial)
        partial.mkdir(parents=True)
        try:
            result = self._guarded(stage, lambda: stage.run(ctx, partial))
            ctx.cancel.raise_if_cancelled()
            (partial / RESULT_FILE).write_text(
                json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            if out_dir.exists():
                shutil.rmtree(out_dir)
            partial.rename(out_dir)
        except BaseException:
            shutil.rmtree(partial, ignore_errors=True)
            raise
        self._guarded(stage, lambda: stage.publish(ctx, out_dir, result))
        _prune(stage_dir, keep=stage.cache_keep, protect=out_dir)
        seconds = time.monotonic() - started
        on_event(StageEvent(stage.name, "finished", key, seconds))
        return StageReport(stage.name, "finished", key, seconds, result)

    @staticmethod
    def _guarded(stage: Stage, action: Callable[[], _T]) -> _T:
        try:
            return action()
        except KaraForgeError:
            raise
        except Exception as exc:
            raise PipelineError(
                f"階段「{stage.title_zh or stage.name}」發生未預期的錯誤。",
                f"Stage '{stage.title_en or stage.name}' failed unexpectedly.",
                hint_zh="加上 --verbose 可以看到詳細的錯誤內容;如果問題持續,請回報這段訊息。",
                hint_en="Re-run with --verbose for details; please report this if it persists.",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc


def _read_result(path: Path) -> JsonDict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None  # pyright: ignore[reportUnknownVariableType]


def _prune(stage_dir: Path, *, keep: int, protect: Path) -> None:
    """Delete the least recently used cache entries beyond ``keep`` and stale partial folders."""
    entries: list[tuple[float, Path]] = []
    for child in stage_dir.iterdir():
        if not child.is_dir() or child == protect:
            continue
        if ".partial-" in child.name:
            if time.time() - child.stat().st_mtime > 6 * 3600:
                shutil.rmtree(child, ignore_errors=True)
            continue
        entries.append((child.stat().st_mtime, child))
    entries.sort(reverse=True)
    for _mtime, path in entries[max(0, keep - 1) :]:
        shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "EventFn",
    "JobCancelledError",
    "PipelineRunner",
    "RunReport",
    "StageEvent",
    "StageReport",
]
