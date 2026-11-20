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
    fmt: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="輸出格式 / format: mp4, mkv, ass, lrc, elrc, srt, ultrastar, kfproj.",
        ),
    ] = "mp4",
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
    """匯出影片、字幕或歌詞檔 / export a video, subtitles or lyrics."""
    store = open_project(project)
    exported = export_project(
        store, fmt=fmt, audio=audio, res=res, background=background, output=output, profile=profile
    )
    console.print(pick(f"已輸出 [bold]{exported}[/bold]", f"Wrote [bold]{exported}[/bold]"))
    if fmt.strip().lower() == "ultrastar":
        media = store.load().media.source or ""
        suffix = Path(media).suffix or ".mp3"
        console.print(
            pick(
                f"[dim]請把歌曲的媒體檔放在同一個資料夾,並命名為 "
                f"{exported.name.removesuffix('.ultrastar.txt').removesuffix('.txt')}{suffix}[/dim]",
                f"[dim]Put the song's media file next to it, named "
                f"{exported.name.removesuffix('.ultrastar.txt').removesuffix('.txt')}{suffix}[/dim]",
            )
        )


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
    """Export a project and return the path of the written file.

    The file is always produced under the project's ``exports/`` folder; with ``output`` it
    is copied to that path as well, and that path is returned.
    """
    from karaforge.exporting import ExportRequest, export, get_format

    extension = get_format(fmt).suffix
    name: str | None = None
    if output is not None:
        name = (
            output.name.removesuffix(extension) if output.name.endswith(extension) else output.stem
        )
    request = ExportRequest(
        format=fmt,
        audio=audio,
        resolution=parse_resolution(res) if res is not None else None,
        background=background,
        name=name,
    )
    with pipeline_ui() as (on_progress, on_event):
        produced = export(
            store, request, profile=get_profile(profile), progress=on_progress, on_event=on_event
        )
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


@app.command("align")
def align_command(
    project: Annotated[Path, typer.Argument(help="專案資料夾 / project folder.")],
    respect_locked: Annotated[
        bool,
        typer.Option(
            "--respect-locked/--ignore-locked",
            help="保留已鎖定的字作為錨點(預設)/ keep locked tokens as anchors (default).",
        ),
    ] = True,
    line: Annotated[
        list[int] | None,
        typer.Option("--line", help="只重新對齊這幾行(從 1 起算,可重複)/ only these lines."),
    ] = None,
    profile: ProfileOption = DEFAULT_PROFILE,
    settings: SetOption = None,
    verbose: VerboseOption = False,
) -> None:
    """重新對齊歌詞 / align the lyrics again.

    已鎖定的字(在編輯器裡修過、或用打點模式標過的字)不會被移動,而且會當成錨點,
    讓它們之間的字對得更準。加上 --ignore-locked 則先解除所有鎖定、整首重來。
    """
    store = open_project(project)
    document = store.load()
    numbers = sorted(set(line or []))
    invalid = [number for number in numbers if not 1 <= number <= len(document.lines)]
    if invalid:
        raise ProjectError(
            f"沒有第 {'、'.join(str(number) for number in invalid)} 行"
            f"(這個專案有 {len(document.lines)} 行)。",
            f"No such line: {', '.join(str(number) for number in invalid)} "
            f"(the project has {len(document.lines)} lines).",
        )
    locked = sum(token.locked for item in document.lines for token in item.tokens)
    if not respect_locked and locked:
        for item in document.lines:
            for token in item.tokens:
                if token.locked:
                    token.locked = False
                    token.source = "auto"
        store.save(document)
        console.print(
            pick(
                f"已解除 {locked} 個鎖定(上一版存在 project.json.bak)。",
                f"Released {locked} locked tokens (the previous version is in project.json.bak).",
            )
        )
    elif locked:
        console.print(
            pick(
                f"保留 {locked} 個已鎖定的字作為錨點。",
                f"Keeping {locked} locked tokens as anchors.",
            )
        )
    options: dict[str, Any] = {}
    if numbers:
        options["align_only_lines"] = [document.lines[number - 1].id for number in numbers]
    report = _run(
        store,
        resolve_profile(profile, settings),
        targets=("align",),
        force_from="align",
        options=options,
    )
    _print_summary(store, report)


@app.command("batch")
def batch_command(
    folder: Annotated[Path, typer.Argument(help="放歌曲與歌詞的資料夾 / folder with songs.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="輸出資料夾 / output folder.")],
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="輸出格式 / format: mp4, mkv, ass, lrc, …")
    ] = "mp4",
    profile: ProfileOption = DEFAULT_PROFILE,
    audio: Annotated[
        str, typer.Option("--audio", help="instrumental、guide:-12db、original.")
    ] = "instrumental",
    res: Annotated[str | None, typer.Option("--res", help="解析度 / resolution.")] = None,
    language: Annotated[str | None, typer.Option("--language", help="歌曲語言 / language.")] = None,
    transcribe: Annotated[
        bool,
        typer.Option(
            "--transcribe/--skip-without-lyrics",
            help="沒有歌詞檔的歌用語音辨識產生草稿 / draft missing lyrics by speech recognition.",
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="只列出會做什麼 / only list what would be done.")
    ] = False,
    settings: SetOption = None,
    verbose: VerboseOption = False,
) -> None:
    """批次處理資料夾:同名的媒體檔與歌詞檔配成一首 / process every song of a folder.

    每首歌的專案放在輸出資料夾裡(歌名.kfproj),所以中斷後再執行一次會從停下來的地方繼續;
    一首失敗不會影響其他首,最後列出結果,有失敗時結束代碼為 1。
    """
    import json
    import time

    from rich.table import Table

    from karaforge.batch import plan_batch, project_dir_for
    from karaforge.exporting import get_format
    from karaforge.project.create import create_or_update_project
    from karaforge.stages.standard import PROCESS_TARGETS

    plan = plan_batch(folder)
    extension = get_format(fmt).suffix
    chosen = resolve_profile(profile, settings)
    for path in plan.duplicates:
        console.print(
            pick(
                f"[yellow]略過 {path.name}:同名的媒體檔已經有一個。[/yellow]",
                f"[yellow]Skipping {path.name}: another media file has the same name.[/yellow]",
            )
        )
    for path in plan.unmatched_lyrics:
        console.print(
            pick(
                f"[yellow]{path.name} 沒有同名的媒體檔。[/yellow]",
                f"[yellow]{path.name} has no media file of the same name.[/yellow]",
            )
        )
    if not plan.items:
        raise ProjectError(
            f"{folder} 裡沒有可以處理的媒體檔。",
            f"No media files to process in {folder}.",
            hint_zh="把歌曲(mp3、wav、mp4…)和同名的歌詞檔(.txt、.lrc…)放進資料夾。",
            hint_en="Put songs (mp3, wav, mp4, …) and same-named lyrics (.txt, .lrc, …) in it.",
        )

    results: list[dict[str, Any]] = []
    failed = False
    for number, item in enumerate(plan.items, start=1):
        target = out / f"{item.name}{extension}"
        entry: dict[str, Any] = {
            "name": item.name,
            "media": str(item.media),
            "lyrics": str(item.lyrics) if item.lyrics else None,
            "output": str(target),
        }
        results.append(entry)
        console.rule(f"[bold]{number}/{len(plan.items)}  {item.name}")
        if item.lyrics is None and not transcribe:
            entry["status"] = "skipped"
            entry["reason"] = pick("沒有歌詞檔", "no lyrics file")
            console.print(
                pick(
                    "  [yellow]沒有同名的歌詞檔,略過"
                    "(加上 --transcribe 可用語音辨識產生草稿)。[/yellow]",
                    "  [yellow]No lyrics file of the same name; skipped "
                    "(--transcribe drafts them by speech recognition).[/yellow]",
                )
            )
            continue
        if dry_run:
            entry["status"] = "planned"
            source = item.lyrics.name if item.lyrics else pick("語音辨識", "speech recognition")
            console.print(f"  {item.media.name} + {source} → {target}")
            continue
        started = time.monotonic()
        try:
            store, _created = create_or_update_project(
                item.media, project_dir_for(item, out), lyrics=item.lyrics, language=language
            )
            _run(store, chosen, targets=PROCESS_TARGETS)
            export_project(store, fmt=fmt, audio=audio, res=res, output=target, profile=profile)
            document = store.load()
            tokens = [token for row in document.lines for token in row.tokens]
            entry["status"] = "done"
            entry["tokens"] = len(tokens)
            entry["low_confidence"] = sum(
                (token.confidence or 0.0) < 0.5 and not token.locked
                for token in tokens
                if token.is_timed
            )
        except KaraForgeError as error:
            failed = True
            entry["status"] = "failed"
            entry["reason"] = pick(error.message_zh, error.message_en)
            report_error(error, verbose=verbose)
        entry["seconds"] = round(time.monotonic() - started, 1)

    table = Table(show_edge=False)
    for column in (
        pick("歌曲", "Song"),
        pick("結果", "Result"),
        pick("字數", "Tokens"),
        pick("建議檢查", "To check"),
        pick("時間", "Time"),
        pick("說明", "Note"),
    ):
        table.add_column(column)
    labels = {
        "done": pick("[green]完成[/green]", "[green]done[/green]"),
        "failed": pick("[red]失敗[/red]", "[red]failed[/red]"),
        "skipped": pick("[yellow]略過[/yellow]", "[yellow]skipped[/yellow]"),
        "planned": pick("預定", "planned"),
    }
    for entry in results:
        table.add_row(
            entry["name"],
            labels[entry["status"]],
            str(entry.get("tokens", "")),
            str(entry.get("low_confidence", "")),
            f"{entry['seconds']:.0f}s" if "seconds" in entry else "",
            entry.get("reason", ""),
        )
    console.print()
    console.print(table)
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
        report_path = out / "batch-report.json"
        report_path.write_text(
            json.dumps(
                {"profile": profile, "format": fmt, "songs": results}, ensure_ascii=False, indent=1
            ),
            encoding="utf-8",
        )
        console.print(pick(f"[dim]紀錄:{report_path}[/dim]", f"[dim]Report: {report_path}[/dim]"))
    if failed:
        raise typer.Exit(1)


ENV_WORKSPACE = "KARAFORGE_WORKSPACE"


@app.command("serve")
def serve_command(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="放專案的資料夾(預設:目前的資料夾)/ folder that holds the projects.",
        ),
    ] = None,
    host: Annotated[
        str, typer.Option("--host", help="監聽位址 / address to listen on.")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="連接埠 / port.")] = 8765,
    profile: ProfileOption = DEFAULT_PROFILE,
    open_browser: Annotated[
        bool, typer.Option("--open", help="啟動後開啟瀏覽器 / open the browser.")
    ] = False,
    verbose: VerboseOption = False,
) -> None:
    """啟動 Web 介面 / start the web app."""
    import os

    import uvicorn

    from karaforge import paths
    from karaforge.server import ServerSettings, create_app

    get_profile(profile)
    root = workspace or Path(os.environ.get(ENV_WORKSPACE) or ".")
    static = paths.bundled_dir("web")
    application = create_app(
        ServerSettings(workspace=root, static_dir=static, default_profile=profile)
    )
    shown_host = "localhost" if host in ("127.0.0.1", "0.0.0.0", "::") else host
    address = f"http://{shown_host}:{port}"
    console.print(
        pick(
            f"KaraForge 已啟動:[bold]{address}[/bold](專案資料夾:{root.resolve()})",
            f"KaraForge is running at [bold]{address}[/bold] (projects in {root.resolve()})",
        )
    )
    if not (static / "index.html").is_file():
        console.print(
            pick(
                "[yellow]找不到已建置的前端,只提供 API。"
                "請在 web/ 執行 npm ci && npm run build。[/yellow]",
                "[yellow]The web app has not been built; only the API is served. "
                "Run npm ci && npm run build in web/.[/yellow]",
            )
        )
    if host not in ("127.0.0.1", "localhost", "::1"):
        console.print(
            pick(
                "[yellow]注意:伺服器沒有登入機制,只應該在信任的網路上對外開放。[/yellow]",
                "[yellow]Note: the server has no authentication; expose it only on a network "
                "you trust.[/yellow]",
            )
        )
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, webbrowser.open, args=(address,)).start()
    uvicorn.run(application, host=host, port=port, log_level="info" if verbose else "warning")


@app.command("bench")
def bench_command(
    suite: Annotated[str, typer.Option("--suite", help="synthetic 或 real。")] = "synthetic",
    split: Annotated[
        str, typer.Option("--split", help="合成測資分組 / split: test, dev, smoke.")
    ] = "test",
    profile: ProfileOption = DEFAULT_PROFILE,
    aligner: Annotated[
        list[str] | None,
        typer.Option("--aligner", help="要比較的對齊器,可重複 / aligner(s) to compare."),
    ] = None,
    settings: SetOption = None,
    language: Annotated[
        list[str] | None, typer.Option("--language", help="zh、en、mixed(可重複)。")
    ] = None,
    snr: Annotated[
        list[int] | None, typer.Option("--snr", help="訊噪比 dB(可重複)/ SNR levels.")
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="每種語言只取前 N 首 / first N songs per language."),
    ] = None,
    ablation: Annotated[
        bool, typer.Option("--ablation", help="加跑消融實驗 / also run the ablation study.")
    ] = False,
    anchors: Annotated[
        bool, typer.Option("--anchors/--no-anchors", help="錨點實驗 / anchor experiment.")
    ] = True,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="報告資料夾。")] = None,
    verbose: VerboseOption = False,
) -> None:
    """執行對齊評測並產生報告 / run the alignment benchmark and write a report."""
    if suite not in ("synthetic", "real"):
        raise ExportError(
            f"沒有這個評測套件:{suite}",
            f"Unknown suite: {suite}",
            hint_zh="可用:synthetic、real。",
            hint_en="Use synthetic or real.",
        )
    try:
        from kfbench.cli import run_bench
    except ImportError as exc:
        from karaforge.errors import DependencyMissingError

        raise DependencyMissingError(
            "評測工具的相依套件沒有安裝。",
            "The benchmark dependencies are not installed.",
            hint_zh="請在原始碼目錄執行:uv sync --extra cpu --group bench",
            hint_en="From a source checkout run: uv sync --extra cpu --group bench",
            detail=str(exc),
        ) from exc
    run_bench(
        suite=suite,
        split=split,
        profile=profile,
        aligners=aligner,
        settings=settings,
        languages=language,
        snr_levels=snr,
        limit=limit,
        ablation=ablation,
        anchors=anchors,
        output=output,
        console=console,
    )


@app.command("ruby")
def ruby_command(
    project: Annotated[Path, typer.Argument(help="專案資料夾 / project folder.")],
    kind: Annotated[
        str | None,
        typer.Option("--kind", "-k", help="zhuyin(注音)或 pinyin(拼音);省略則沿用目前的。"),
    ] = None,
    clear: Annotated[
        bool, typer.Option("--clear", help="移除自動讀音 / remove the automatic readings.")
    ] = False,
) -> None:
    """產生注音或拼音 / give Chinese lyrics their readings (zhuyin or pinyin).

    手動指定的讀音不會被更動。要不要顯示由主題的 ruby.enabled 決定。
    """
    from karaforge.text.ruby import KINDS, annotate_project, clear_project, default_kind, kind_of

    store = open_project(project)
    document = store.load()
    if clear:
        removed = clear_project(document)
        store.save(document)
        console.print(
            pick(f"已移除 {removed} 個自動讀音。", f"Removed {removed} automatic readings.")
        )
        return
    chosen = kind.strip().lower() if kind else None
    if chosen is not None and chosen not in KINDS:
        raise ProjectError(
            f"沒有這種讀音:{kind}",
            f"Unknown kind of reading: {kind}",
            hint_zh="可用:zhuyin(注音)、pinyin(拼音)。",
            hint_en="Use zhuyin or pinyin.",
        )
    resolved = chosen or kind_of(document.lines) or default_kind(document.meta.language)
    if resolved is None:
        raise ProjectError(
            f"這個專案的語言是 {document.meta.language},不會自動產生國語讀音。",
            f"The project language is {document.meta.language}; Mandarin readings are not "
            "generated for it automatically.",
            hint_zh="如果歌詞確實是國語,請加上 --kind zhuyin 或 --kind pinyin。",
            hint_en="If the lyrics are Mandarin after all, pass --kind zhuyin or --kind pinyin.",
        )
    count = annotate_project(document, "zhuyin" if resolved == "zhuyin" else "pinyin")
    manual = sum(token.ruby_source == "manual" for item in document.lines for token in item.tokens)
    store.save(document)
    label = pick("注音", "zhuyin") if resolved == "zhuyin" else pick("拼音", "pinyin")
    console.print(
        pick(
            f"已為 {count} 個字標上{label}(另有 {manual} 個手動讀音維持不變)。",
            f"{count} characters now have {label} readings ({manual} manual readings were kept).",
        )
    )
    console.print(
        pick(
            "[dim]破音字不一定正確(見 docs/ruby.md);可在歌詞裡用 字{讀音} 或在編輯器修正。"
            "顯示與否由主題的 ruby.enabled 決定。[/dim]",
            "[dim]Polyphonic characters may be wrong (see docs/ruby.md); correct them with "
            "char{reading} in the lyrics or in the editor.  The theme's ruby.enabled decides "
            "whether readings are shown.[/dim]",
        )
    )


@app.command("doctor")
def doctor_command(
    models: Annotated[
        bool, typer.Option("--models/--no-models", help="檢查模型是否已下載 / check the models.")
    ] = True,
    as_json: Annotated[bool, typer.Option("--json", help="輸出 JSON / print JSON.")] = False,
) -> None:
    """檢查環境與依賴 / check the environment and the dependencies."""
    import json

    from karaforge.doctor import run_checks, worst

    checks = run_checks(models=models)
    overall = worst(checks)
    if as_json:
        payload = {"status": overall, "checks": [check.to_dict() for check in checks]}
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        marks = {"ok": "[green]✓[/green]", "warn": "[yellow]![/yellow]", "fail": "[red]✗[/red]"}
        for check in checks:
            console.print(
                f"  {marks[check.status]} {pick(check.message_zh, check.message_en)}",
                highlight=False,
            )
            hint = pick(check.hint_zh or "", check.hint_en or "")
            if hint:
                console.print(f"      [dim]{hint}[/dim]", highlight=False)
        console.print(
            {
                "ok": pick("[green]一切就緒。[/green]", "[green]Everything is ready.[/green]"),
                "warn": pick(
                    "[yellow]可以使用,但有需要留意的地方。[/yellow]",
                    "[yellow]Usable, with the points marked ! above.[/yellow]",
                ),
                "fail": pick(
                    "[red]有問題需要先解決(標示 ✗ 的項目)。[/red]",
                    "[red]The items marked ✗ need fixing first.[/red]",
                ),
            }[overall]
        )
    if overall == "fail":
        raise typer.Exit(1)


models_app = typer.Typer(
    help="管理模型權重 / manage model weights.", no_args_is_help=True, add_completion=False
)
app.add_typer(models_app, name="models")


def profile_model_ids(profile: Profile) -> list[str]:
    """Registry ids of every model a profile needs, including required companions."""
    from karaforge.adapters.registry import profile_model_ids as model_ids

    return model_ids(profile)


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
