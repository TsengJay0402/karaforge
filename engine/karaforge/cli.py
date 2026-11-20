"""The ``kf`` command line interface.

Commands are thin wrappers around the engine; see ``docs/cli.md`` for the full reference.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from karaforge import __version__
from karaforge.errors import ExportError, KaraForgeError, ProjectError
from karaforge.i18n import current_lang, pick
from karaforge.pipeline.profiles import DEFAULT_PROFILE, Profile, get_profile, parse_overrides
from karaforge.pipeline.runner import EventFn, RunReport, StageEvent
from karaforge.project.store import PROJECT_SUFFIX, ProjectStore
from karaforge.runtime import ProgressFn

app = typer.Typer(
    name="kf",
    help="KaraForge:把歌曲與歌詞變成 KTV 影片 / turn a song and its lyrics into a karaoke video.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
console = Console()
err_console = Console(stderr=True)

RESOLUTIONS = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "2160p": (3840, 2160),
    "4k": (3840, 2160),
}

ProfileOption = Annotated[
    str,
    typer.Option(
        "--profile", "-p", help="處理品質設定檔 / profile: cpu-lite, balanced, gpu-quality."
    ),
]
SetOption = Annotated[
    list[str] | None,
    typer.Option("--set", help="覆寫設定 / override a setting, e.g. align.onset_snap_ms=80."),
]
VerboseOption = Annotated[
    bool, typer.Option("--verbose", "-v", help="顯示詳細錯誤 / show error details.")
]


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"KaraForge {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="顯示版本 / show the version and exit.",
        ),
    ] = False,
) -> None:
    """Global options."""


def report_error(error: KaraForgeError, *, verbose: bool = False) -> None:
    """Print a user-facing error message to stderr."""
    lang = current_lang()
    label = "錯誤" if lang == "zh" else "Error"
    err_console.print(f"[bold red]{label}:[/bold red] {error.user_message(lang)}", highlight=False)
    if error.detail:
        if verbose:
            err_console.print(f"[dim]{error.detail}[/dim]", highlight=False, markup=False)
        else:
            err_console.print(
                pick(
                    "[dim](加上 --verbose 看詳細內容)[/dim]",
                    "[dim](add --verbose for details)[/dim]",
                )
            )


def resolve_profile(name: str, overrides: list[str] | None) -> Profile:
    """Build the profile for a run from its name and ``--set`` overrides."""
    profile = get_profile(name)
    return profile.with_overrides(parse_overrides(overrides)) if overrides else profile


def open_project(path: Path) -> ProjectStore:
    """Open an existing project folder.

    Raises:
        ProjectError: If the folder is not a KaraForge project.
    """
    store = ProjectStore(path)
    if not store.exists():
        raise ProjectError(
            f"找不到專案:{path}",
            f"Not a KaraForge project: {path}",
            hint_zh="請指定 .kfproj 資料夾,或先用 `kf new` 建立專案。",
            hint_en="Pass a .kfproj folder, or create one with `kf new`.",
        )
    return store


def parse_resolution(value: str) -> tuple[int, int]:
    """Parse ``1080p`` or ``1920x1080`` into a (width, height) pair.

    Raises:
        ExportError: If the value is not a known preset or a valid size.
    """
    key = value.strip().lower()
    if key in RESOLUTIONS:
        return RESOLUTIONS[key]
    width, separator, height = key.partition("x")
    if separator and width.isdigit() and height.isdigit():
        size = (int(width), int(height))
        if size[0] >= 160 and size[1] >= 90 and size[0] % 2 == 0 and size[1] % 2 == 0:
            return size
    raise ExportError(
        f"看不懂的解析度:{value}",
        f"Unrecognised resolution: {value}",
        hint_zh="可用:" + "、".join(RESOLUTIONS) + ",或寬x高(偶數),例如 1920x1080。",
        hint_en="Use one of " + ", ".join(RESOLUTIONS) + " or WIDTHxHEIGHT (even numbers).",
    )


@contextmanager
def pipeline_ui() -> Generator[tuple[ProgressFn, EventFn]]:
    """A progress bar plus one printed line per finished stage."""
    from karaforge.stages.standard import all_stages

    titles = {
        stage.name: pick(stage.title_zh, stage.title_en) or stage.name for stage in all_stages()
    }
    progress = Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
    state = {"stage": ""}
    with progress:
        task = progress.add_task(pick("準備中", "Preparing"), total=1000)

        def on_progress(fraction: float, message: str = "") -> None:
            label = titles.get(state["stage"], state["stage"])
            detail = message.split(" / ")[0 if current_lang() == "zh" else -1] if message else ""
            progress.update(
                task,
                completed=round(fraction * 1000),
                description=f"{label} {detail}".strip() or pick("處理中", "Working"),
            )

        def on_event(event: StageEvent) -> None:
            title = titles.get(event.stage, event.stage)
            if event.status == "started":
                state["stage"] = event.stage
                progress.update(task, description=title)
            elif event.status == "finished":
                progress.console.print(
                    f"  [green]✓[/green] {title}  [dim]{event.seconds:.1f}s[/dim]"
                )
            elif event.status == "cached":
                progress.console.print(
                    f"  [cyan]↺[/cyan] {title}  [dim]{pick('快取', 'cached')}[/dim]"
                )
            elif event.status == "skipped":
                progress.console.print(f"  [dim]– {title}  {pick('略過', 'skipped')}[/dim]")

        yield on_progress, on_event


def _run(
    store: ProjectStore,
    profile: Profile,
    *,
    targets: tuple[str, ...] | None,
    force_from: str | None = None,
    options: dict[str, Any] | None = None,
    include_dependencies: bool = True,
) -> RunReport:
    from karaforge.stages.standard import run_pipeline

    with pipeline_ui() as (on_progress, on_event):
        return run_pipeline(
            store,
            profile=profile,
            targets=targets,
            force_from=force_from,
            options=options,
            progress=on_progress,
            on_event=on_event,
            include_dependencies=include_dependencies,
        )


@app.command("new")
def new_command(
    media: Annotated[Path, typer.Argument(help="影片或音檔 / video or audio file.")],
    lyrics: Annotated[
        Path | None,
        typer.Option("--lyrics", "-l", help="歌詞檔(.txt);省略則用語音辨識產生草稿 / lyrics file."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="專案資料夾 / project folder (.kfproj).")
    ] = None,
    language: Annotated[
        str | None, typer.Option("--language", help="歌曲語言 / language, e.g. zh-TW, en.")
    ] = None,
    title: Annotated[str | None, typer.Option("--title", help="歌名 / song title.")] = None,
    artist: Annotated[str | None, typer.Option("--artist", help="歌手 / artist.")] = None,
    force: Annotated[bool, typer.Option("--force", help="覆寫既有專案 / overwrite.")] = False,
) -> None:
    """建立新專案 / create a project from a media file and lyrics."""
    from karaforge.project.create import create_project, default_project_dir

    target = output or default_project_dir(media)
    store = create_project(
        media, target, lyrics=lyrics, language=language, title=title, artist=artist, overwrite=force
    )
    project = store.load()
    console.print(
        pick(
            f"已建立專案 [bold]{store.root}[/bold]({len(project.lines)} 行歌詞)。"
            f"\n下一步:kf run {store.root}",
            f"Created project [bold]{store.root}[/bold] ({len(project.lines)} lyric lines)."
            f"\nNext: kf run {store.root}",
        )
    )


@app.command("run")
def run_command(
    project: Annotated[Path, typer.Argument(help="專案資料夾 / project folder.")],
    profile: ProfileOption = DEFAULT_PROFILE,
    from_stage: Annotated[
        str | None,
        typer.Option("--from", help="從這個階段開始強制重跑 / force re-run from this stage."),
    ] = None,
    settings: SetOption = None,
    verbose: VerboseOption = False,
) -> None:
    """執行處理管線:分離、辨識、對齊 / run the pipeline: separate, transcribe, align."""
    from karaforge.stages.standard import PROCESS_TARGETS

    store = open_project(project)
    report = _run(
        store, resolve_profile(profile, settings), targets=PROCESS_TARGETS, force_from=from_stage
    )
    _print_summary(store, report)


def _print_summary(store: ProjectStore, report: RunReport) -> None:
    project = store.load()
    tokens = [token for line in project.lines for token in line.tokens]
    timed = [token for token in tokens if token.is_timed]
    doubtful = [token for token in timed if (token.confidence or 0.0) < 0.5 and not token.locked]
    console.print(
        pick(
            f"完成:{len(project.lines)} 行、{len(tokens)} 個字,已對齊 {len(timed)} 個;"
            f"其中 {len(doubtful)} 個信心度偏低,建議在編輯器檢查。",
            f"Done: {len(project.lines)} lines, {len(tokens)} tokens, {len(timed)} aligned; "
            f"{len(doubtful)} have low confidence and are worth checking in the editor.",
        )
    )
    del report


@app.command("export")
def export_command(
    project: Annotated[Path, typer.Argument(help="專案資料夾 / project folder.")],
    fmt: Annotated[str, typer.Option("--format", "-f", help="輸出格式 / format: mp4.")] = "mp4",
    audio: Annotated[
        str,
        typer.Option("--audio", help="instrumental、guide:-12db、original."),
    ] = "instrumental",
    res: Annotated[
        str | None, typer.Option("--res", help="解析度 / resolution: 720p, 1080p, 1920x1080.")
    ] = None,
    background: Annotated[
        str | None, typer.Option("--background", help="背景:video、color、image、blur。")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="輸出檔 / output file.")
    ] = None,
    profile: ProfileOption = DEFAULT_PROFILE,
    verbose: VerboseOption = False,
) -> None:
    """匯出影片 / export the karaoke video."""
    store = open_project(project)
    exported = export_project(
        store, fmt=fmt, audio=audio, res=res, background=background, output=output, profile=profile
    )
    console.print(pick(f"已輸出 [bold]{exported}[/bold]", f"Wrote [bold]{exported}[/bold]"))


def export_project(
    store: ProjectStore,
    *,
    fmt: str = "mp4",
    audio: str = "instrumental",
    res: str | None = None,
    background: str | None = None,
    output: Path | None = None,
    profile: str = DEFAULT_PROFILE,
) -> Path:
    """Export a project and return the path of the written file."""
    from karaforge.io.exporters.video import VideoOptions, parse_audio_option
    from karaforge.layout.theme import load_theme
    from karaforge.project.store import slugify
    from karaforge.stages.export import OPTION_KEY, OUTPUT_NAME_KEY
    from karaforge.stages.standard import EXPORT_TARGETS

    if fmt.lower() != "mp4":
        raise ExportError(
            f"還不支援的匯出格式:{fmt}",
            f"Unsupported export format: {fmt}",
            hint_zh="目前可用:mp4。",
            hint_en="Available: mp4.",
        )
    document = store.load()
    if res is not None:
        size = parse_resolution(res)
        if tuple(document.render.resolution) != size:
            document.render.resolution = size
            store.save(document)
    theme = load_theme(document.style.theme).with_overrides(document.style.overrides)
    mode, level = parse_audio_option(audio)
    kind = (background or document.render.background.type).lower()
    if kind not in ("video", "image", "color", "blur"):
        raise ExportError(
            f"看不懂的背景選項:{kind}",
            f"Unrecognised background: {kind}",
            hint_zh="可用:video、color、image、blur。",
            hint_en="Use video, color, image or blur.",
        )
    options = VideoOptions(
        audio=mode,
        guide_db=level,
        background=kind,
        color=document.render.background.color or theme.background.color,
        image=document.render.background.image,
        dim_bottom=theme.background.dim_bottom,
    )
    name = slugify(output.stem if output is not None else document.meta.title or "karaoke")
    _run(
        store,
        get_profile(profile),
        targets=EXPORT_TARGETS,
        options={OPTION_KEY: options, OUTPUT_NAME_KEY: name},
        include_dependencies=False,
    )
    produced = store.paths.exports / f"{name}.mp4"
    if output is None:
        return produced
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, output)
    return output


@app.command("auto")
def auto_command(
    media: Annotated[Path, typer.Argument(help="影片或音檔 / video or audio file.")],
    lyrics: Annotated[
        Path | None, typer.Argument(help="歌詞檔;省略則用語音辨識 / lyrics file (optional).")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="輸出影片 / output video.")
    ] = None,
    profile: ProfileOption = DEFAULT_PROFILE,
    audio: Annotated[
        str, typer.Option("--audio", help="instrumental、guide:-12db、original.")
    ] = "instrumental",
    res: Annotated[str | None, typer.Option("--res", help="解析度 / resolution.")] = None,
    language: Annotated[str | None, typer.Option("--language", help="歌曲語言 / language.")] = None,
    settings: SetOption = None,
    verbose: VerboseOption = False,
) -> None:
    """全自動:媒體 + 歌詞 → KTV 影片 / one command from media and lyrics to a video."""
    from karaforge.project.create import create_or_update_project
    from karaforge.stages.standard import PROCESS_TARGETS

    target = output or media.with_name(f"{media.stem}-ktv.mp4")
    project_dir = target.with_name(target.stem + PROJECT_SUFFIX)
    store, created = create_or_update_project(media, project_dir, lyrics=lyrics, language=language)
    console.print(
        pick(
            f"{'建立' if created else '沿用'}專案 [bold]{store.root}[/bold]",
            f"{'Created' if created else 'Reusing'} project [bold]{store.root}[/bold]",
        )
    )
    _run(store, resolve_profile(profile, settings), targets=PROCESS_TARGETS)
    exported = export_project(store, audio=audio, res=res, output=target, profile=profile)
    console.print(pick(f"完成:[bold]{exported}[/bold]", f"Done: [bold]{exported}[/bold]"))


models_app = typer.Typer(
    help="管理模型權重 / manage model weights.", no_args_is_help=True, add_completion=False
)
app.add_typer(models_app, name="models")


def profile_model_ids(profile: Profile) -> list[str]:
    """Registry ids of every model a profile needs, including required companions."""
    from karaforge.adapters.registry import describe_profile
    from karaforge.models.registry import get_model

    ordered: list[str] = []

    def add(model_id: str) -> None:
        for dependency in get_model(model_id).requires:
            add(dependency)
        if model_id not in ordered:
            ordered.append(model_id)

    for info in describe_profile(profile):
        for model_id in info.models:
            add(model_id)
    return ordered


def _size(size: int) -> str:
    return f"{size / 1e6:,.1f} MB" if size >= 1e5 else f"{size / 1e3:,.1f} kB"


@models_app.command("list")
def models_list() -> None:
    """列出已知的模型與安裝狀態 / list known models and whether they are installed."""
    from rich.table import Table

    from karaforge.models import is_installed, load_registry

    table = Table(show_edge=False)
    for column in (
        pick("模型", "Model"),
        pick("類型", "Kind"),
        pick("大小", "Size"),
        pick("授權", "Licence"),
        pick("狀態", "Status"),
        pick("說明", "Title"),
    ):
        table.add_column(column)
    for spec in load_registry().values():
        status = (
            pick("[green]已安裝[/green]", "[green]installed[/green]") if is_installed(spec) else "—"
        )
        licence = spec.license if spec.commercial_use else f"[yellow]{spec.license}[/yellow]"
        table.add_row(spec.id, spec.kind, _size(spec.total_size), licence, status, spec.title)
    console.print(table)
    console.print(
        pick(
            "黃色授權代表不允許商業使用,下載時需要加上 --accept-license。",
            "A licence shown in yellow forbids commercial use; downloading needs --accept-license.",
        )
    )


@models_app.command("download")
def models_download(
    names: Annotated[list[str] | None, typer.Argument(help="模型名稱 / model ids.")] = None,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile", "-p", help="下載某個設定檔需要的全部模型 / all models of a profile."
        ),
    ] = None,
    accept_license: Annotated[
        bool,
        typer.Option("--accept-license", help="同意非商業授權 / accept non-commercial licences."),
    ] = False,
) -> None:
    """下載模型(可續傳,並驗證檢查碼)/ download models (resumable, checksum-verified)."""
    import os

    from karaforge.models import download, get_model, is_installed
    from karaforge.models.store import ENV_ACCEPT_LICENSES

    wanted = list(names or [])
    if profile is not None:
        wanted += profile_model_ids(get_profile(profile))
    if not wanted:
        wanted = profile_model_ids(get_profile(DEFAULT_PROFILE))
    if accept_license:
        os.environ[ENV_ACCEPT_LICENSES] = ",".join(wanted)
    for model_id in dict.fromkeys(wanted):
        spec = get_model(model_id)
        if is_installed(spec):
            console.print(f"  [cyan]↺[/cyan] {model_id}  {pick('已安裝', 'already installed')}")
            continue
        with Progress(
            TextColumn("[bold]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"{model_id} ({_size(spec.total_size)})", total=1000)

            def report(
                fraction: float, _label: str = "", _progress: Progress = progress, _task: Any = task
            ) -> None:
                _progress.update(_task, completed=round(fraction * 1000))

            download(spec, progress=report)
        console.print(f"  [green]✓[/green] {model_id}  {_size(spec.total_size)}")


@models_app.command("verify")
def models_verify(
    names: Annotated[list[str] | None, typer.Argument(help="模型名稱 / model ids.")] = None,
) -> None:
    """用檢查碼驗證已下載的模型 / verify downloaded models against their checksums."""
    from karaforge.models import get_model, is_installed, load_registry, verify
    from karaforge.models.store import model_dir

    specs = [get_model(name) for name in names] if names else list(load_registry().values())
    failed = False
    for spec in specs:
        if not names and not is_installed(spec) and not model_dir(spec).exists():
            continue
        problems = verify(spec)
        if problems:
            failed = True
            console.print(f"  [red]✗[/red] {spec.id}")
            for problem in problems:
                console.print(f"      {problem}", highlight=False)
        else:
            console.print(f"  [green]✓[/green] {spec.id}")
    if failed:
        raise typer.Exit(1)


def main() -> None:
    """Entry point for the ``kf`` console script."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    try:
        app()
    except KaraForgeError as error:
        report_error(error, verbose=verbose)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
