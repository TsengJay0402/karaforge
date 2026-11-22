"""The FastAPI application: JSON API, media streaming, events and the bundled web app."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import mimetypes
import os
import shutil
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from karaforge import __version__
from karaforge.errors import (
    ExportError,
    KaraForgeError,
    PipelineError,
    ProjectError,
    RevisionConflictError,
    ThemeError,
)
from karaforge.pipeline.profiles import DEFAULT_PROFILE, Profile, get_profile, profile_names
from karaforge.pipeline.runner import StageEvent
from karaforge.project.schema import Line, Project
from karaforge.project.store import ProjectStore
from karaforge.server.events import EventBus
from karaforge.server.jobs import FINISHED, Job, JobManager
from karaforge.server.workspace import ProjectNotFoundError, Workspace
from karaforge.text.ruby import (
    annotate_line,
    annotate_project,
    clear_line,
    kind_of,
    uses_taiwan_readings,
)
from karaforge.text.script import script_config

MEDIA_NAMES = ("source", "audio", "vocals", "instrumental")
STEMS = ("audio", "vocals", "instrumental")
_KEEP_ALIVE_S = 15.0
_THEME_NAME = r"^[a-z0-9][a-z0-9-]{0,39}$"


@dataclass(frozen=True)
class ServerSettings:
    """How the server is set up."""

    workspace: Path
    """Folder that holds the ``*.kfproj`` projects."""
    static_dir: Path | None = None
    """Built web app to serve at ``/``; the API alone is served when ``None``."""
    default_profile: str = DEFAULT_PROFILE


# ------------------------------------------------------------------------- request bodies


class SaveBody(BaseModel):
    """A project document together with the revision it was based on."""

    project: dict[str, Any]
    revision: int


class LyricsBody(BaseModel):
    """New lyrics for a project, in any supported format."""

    text: str
    filename: str = "lyrics.txt"
    revision: int


class LinkBody(BaseModel):
    """A video link to look up."""

    url: str


class RetokenizeBody(BaseModel):
    """A line and its edited text."""

    line: dict[str, Any]
    text: str
    language: str | None = None


class RubyBody(BaseModel):
    """Lines to give automatic readings to (or to take them from, with ``none``)."""

    lines: list[dict[str, Any]]
    kind: Literal["zhuyin", "pinyin", "none"] = "zhuyin"
    language: str = "zh-TW"


class PreviewBody(BaseModel):
    """What to render a preview of: the saved project, or an unsaved draft of it."""

    project: dict[str, Any] | None = None
    resolution: tuple[int, int] | None = None


class JobBody(BaseModel):
    """A processing or re-alignment request."""

    kind: Literal["process", "align"] = "process"
    profile: str | None = None
    from_stage: str | None = None
    lines: list[str] | None = None
    settings: dict[str, Any] = Field(default_factory=dict[str, Any])


class ExportBody(BaseModel):
    """An export request."""

    format: str = "mp4"
    audio: str = "instrumental"
    resolution: tuple[int, int] | None = None
    background: str | None = None
    name: str | None = None
    profile: str | None = None


class ModelsBody(BaseModel):
    """Which models to download."""

    profile: str | None = None
    ids: list[str] = Field(default_factory=list[str])
    accept_license: bool = False


# ------------------------------------------------------------------------------ the app


def _status_of(error: KaraForgeError) -> int:
    if isinstance(error, ProjectNotFoundError):
        return 404
    if isinstance(error, RevisionConflictError):
        return 409
    if error.code == "internal_error":
        return 500
    return 400


def create_app(settings: ServerSettings) -> FastAPI:
    """Build the application for a workspace."""
    workspace = Workspace(settings.workspace)
    bus = EventBus()

    def profile_for(name: str | None, overrides: dict[str, Any] | None = None) -> Profile:
        profile = get_profile(name or settings.default_profile)
        return profile.with_overrides(overrides) if overrides else profile

    def run_job(
        job: Job, progress: Callable[[float, str], None], on_stage: Callable[[StageEvent], None]
    ) -> dict[str, Any]:
        params = job.params
        if job.kind == "models":
            return _download_models(params, progress, job)
        if job.kind == "import":
            return import_from_link(job, progress)
        assert job.project_id is not None
        store = workspace.store(job.project_id)
        profile = profile_for(params.get("profile"), params.get("settings"))
        try:
            if job.kind == "export":
                from karaforge.exporting import ExportRequest, export

                resolution = params.get("resolution")
                path = export(
                    store,
                    ExportRequest(
                        format=str(params.get("format", "mp4")),
                        audio=str(params.get("audio", "instrumental")),
                        resolution=(int(resolution[0]), int(resolution[1])) if resolution else None,
                        background=params.get("background"),
                        name=params.get("name"),
                    ),
                    profile=profile,
                    progress=progress,
                    cancel=job.cancel,
                    on_event=on_stage,
                )
                return {"file": path.name, "bytes": path.stat().st_size}
            from karaforge.stages.standard import PROCESS_TARGETS, run_pipeline

            options: dict[str, Any] = {}
            if job.kind == "align" and params.get("lines"):
                options["align_only_lines"] = list(params["lines"])
            report = run_pipeline(
                store,
                profile=profile,
                targets=("align",) if job.kind == "align" else PROCESS_TARGETS,
                force_from=params.get("from_stage"),
                options=options,
                progress=progress,
                cancel=job.cancel,
                on_event=on_stage,
            )
            return {"executed": report.executed, "cached": report.cached}
        finally:
            _project_changed(job.project_id, "job")

    jobs = JobManager(bus, run_job)

    def import_from_link(job: Job, progress: Callable[[float, str], None]) -> dict[str, Any]:
        """Download the video of a link, make a project of it and (optionally) process it."""
        from karaforge.project.create import create_project as make_project
        from karaforge.tools import ytdlp

        params = job.params
        folder = workspace.uploads / str(params["upload"])
        try:
            target = folder / "download"
            target.mkdir(parents=True, exist_ok=True)
            fetched = ytdlp.download(
                str(params["url"]), target, progress=progress, cancel=job.cancel
            )
            job.cancel.raise_if_cancelled()
            title = str(params.get("title") or "") or fetched.title
            artist = str(params.get("artist") or "") or fetched.artist
            lyrics = folder / str(params["lyrics"]) if params.get("lyrics") else None
            project_id = workspace.new_id(title or "video")
            make_project(
                fetched.path,
                workspace.folder(project_id),
                lyrics=lyrics,
                language=str(params.get("language") or "") or None,
                title=title or None,
                artist=artist or None,
            )
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        process: Job | None = None
        if params.get("start"):
            process = jobs.submit("process", project_id, {"profile": params.get("profile")})
        _project_changed(project_id, "created")
        return {"project_id": project_id, "job": process.id if process else None}

    def _project_changed(project_id: str, reason: str) -> None:
        revision: int | None = None
        with contextlib.suppress(KaraForgeError):
            revision = workspace.store(project_id).current_revision()
        bus.publish({"type": "project", "id": project_id, "revision": revision, "reason": reason})

    def summary(project_id: str) -> dict[str, Any]:
        data = workspace.summary(project_id)
        active = jobs.active_for(project_id)
        last = jobs.last_for(project_id)
        data["job"] = active.to_dict() if active else None
        data["last_job"] = last.to_dict() if last else None
        data["has_thumbnail"] = bool(data["has_video"])
        return data

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield
        jobs.shutdown()

    app = FastAPI(title="KaraForge", version=__version__, lifespan=lifespan, docs_url="/api/docs")
    app.state.workspace = workspace
    app.state.jobs = jobs
    app.state.bus = bus

    @app.exception_handler(KaraForgeError)
    async def _engine_error(_request: Request, error: KaraForgeError) -> JSONResponse:
        return JSONResponse({"error": error.to_dict()}, status_code=_status_of(error))

    # ------------------------------------------------------------------------ system

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/system")
    def system() -> dict[str, Any]:
        return _system_info(settings, workspace)

    # ---------------------------------------------------------------------- projects

    @app.get("/api/projects")
    def list_projects() -> dict[str, Any]:
        return {"projects": [summary(project_id) for project_id in workspace.project_ids()]}

    @app.post("/api/projects", status_code=201)
    async def create_project(
        media: Annotated[UploadFile, File()],
        lyrics: Annotated[str | None, Form()] = None,
        lyrics_file: Annotated[UploadFile | None, File()] = None,
        title: Annotated[str | None, Form()] = None,
        artist: Annotated[str | None, Form()] = None,
        language: Annotated[str | None, Form()] = None,
        profile: Annotated[str | None, Form()] = None,
        start: Annotated[bool, Form()] = True,
    ) -> dict[str, Any]:
        from karaforge.project.create import create_project as make_project

        if profile is not None:
            get_profile(profile)  # reject unknown names before anything is written
        upload_dir = workspace.uploads / uuid.uuid4().hex
        upload_dir.mkdir(parents=True)
        try:
            media_name = Path(media.filename or "media").name
            media_path = upload_dir / media_name
            with media_path.open("wb") as target:
                while chunk := await media.read(1 << 20):
                    target.write(chunk)
            lyrics_path: Path | None = None
            if lyrics_file is not None and lyrics_file.filename:
                lyrics_path = upload_dir / ("lyrics" + Path(lyrics_file.filename).suffix.lower())
                lyrics_path.write_bytes(await lyrics_file.read())
            elif lyrics is not None and lyrics.strip():
                lyrics_path = upload_dir / "lyrics.txt"
                lyrics_path.write_text(lyrics, encoding="utf-8")
            project_id = workspace.new_id(title or Path(media_name).stem)
            await asyncio.to_thread(
                make_project,
                media_path,
                workspace.folder(project_id),
                lyrics=lyrics_path,
                language=language or None,
                title=title or None,
                artist=artist or None,
            )
        finally:
            shutil.rmtree(upload_dir, ignore_errors=True)
        job: Job | None = None
        if start:
            job = jobs.submit("process", project_id, {"profile": profile})
        _project_changed(project_id, "created")
        return {"project": summary(project_id), "job": job.to_dict() if job else None}

    @app.post("/api/media/probe")
    async def probe_link(body: LinkBody) -> dict[str, Any]:
        from karaforge.tools import ytdlp

        media = await asyncio.to_thread(ytdlp.probe, body.url)
        return {"media": media.to_dict()}

    @app.post("/api/projects/import", status_code=202)
    async def import_project(
        url: Annotated[str, Form()],
        lyrics: Annotated[str | None, Form()] = None,
        lyrics_file: Annotated[UploadFile | None, File()] = None,
        title: Annotated[str | None, Form()] = None,
        artist: Annotated[str | None, Form()] = None,
        language: Annotated[str | None, Form()] = None,
        profile: Annotated[str | None, Form()] = None,
        start: Annotated[bool, Form()] = True,
    ) -> dict[str, Any]:
        from karaforge.io.importers import load_lyrics
        from karaforge.tools import ytdlp

        # Everything that can be refused is refused now, not after a long download.
        if profile is not None:
            get_profile(profile)
        address = ytdlp.require_url(url)
        ytdlp.find_ytdlp()
        upload = uuid.uuid4().hex
        folder = workspace.uploads / upload
        folder.mkdir(parents=True)
        try:
            lyrics_name: str | None = None
            if lyrics_file is not None and lyrics_file.filename:
                lyrics_name = "lyrics" + Path(lyrics_file.filename).suffix.lower()
                (folder / lyrics_name).write_bytes(await lyrics_file.read())
            elif lyrics is not None and lyrics.strip():
                lyrics_name = "lyrics.txt"
                (folder / lyrics_name).write_text(lyrics, encoding="utf-8")
            if lyrics_name is not None:
                load_lyrics(folder / lyrics_name)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        job = jobs.submit(
            "import",
            None,
            {
                "url": address,
                "title": (title or "").strip(),
                "artist": (artist or "").strip(),
                "language": language or "",
                "profile": profile,
                "start": start,
                "upload": upload,
                "lyrics": lyrics_name,
            },
        )
        return {"job": job.to_dict()}

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        store = workspace.store(project_id)
        project = store.load()
        return {
            "summary": summary(project_id),
            "project": project.model_dump(mode="json"),
            "media": _media_urls(project_id, store, project),
            "exports": _export_files(project_id, store),
        }

    @app.put("/api/projects/{project_id}")
    def save_project(project_id: str, body: SaveBody) -> dict[str, Any]:
        store = workspace.store(project_id)
        try:
            project = Project.model_validate(body.project)
        except ValueError as error:
            raise ProjectError(
                "送來的專案內容不符合格式，沒有儲存。",
                "The submitted project is not valid; nothing was saved.",
                detail=str(error),
            ) from error
        store.save(project, expected_revision=body.revision)
        _project_changed(project_id, "saved")
        return {"revision": store.current_revision(), "summary": summary(project_id)}

    @app.put("/api/projects/{project_id}/lyrics")
    def replace_lyrics(project_id: str, body: LyricsBody) -> dict[str, Any]:
        from karaforge.io.importers import LYRICS_EXTENSIONS, load_lyrics

        store = workspace.store(project_id)
        suffix = Path(body.filename).suffix.lower()
        scratch = workspace.uploads / uuid.uuid4().hex
        scratch.mkdir(parents=True)
        try:
            path = scratch / f"lyrics{suffix if suffix in LYRICS_EXTENSIONS else '.txt'}"
            path.write_text(body.text, encoding="utf-8")
            parsed = load_lyrics(path)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        project = store.load()
        parsed.apply_meta(project.meta)
        project.singers = parsed.singers
        kind = kind_of(project.lines)
        project.lines = parsed.lines
        project.meta.lyrics_source = "user"
        annotate_project(project, kind)
        store.save(project, expected_revision=body.revision)
        _project_changed(project_id, "saved")
        return {
            "revision": store.current_revision(),
            "project": store.load().model_dump(mode="json"),
        }

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: str) -> Response:
        workspace.store(project_id)
        if jobs.active_for(project_id) is not None:
            raise ProjectError(
                "這個專案還有工作在執行，請先取消再刪除。",
                "A job is still running for this project; cancel it before deleting.",
            )
        workspace.delete(project_id)
        bus.publish({"type": "project", "id": project_id, "revision": None, "reason": "deleted"})
        return Response(status_code=204)

    @app.post("/api/tools/retokenize")
    def retokenize(body: RetokenizeBody) -> dict[str, Any]:
        from karaforge.project.edit import retokenize_line

        try:
            line = Line.model_validate(body.line)
        except ValueError as error:
            raise ProjectError(
                "這一行的內容不符合格式。", "The line is not valid.", detail=str(error)
            ) from error
        edited = retokenize_line(line, body.text, language=body.language)
        return {"line": edited.model_dump(mode="json")}

    @app.post("/api/tools/ruby")
    def ruby_readings(body: RubyBody) -> dict[str, Any]:
        """Automatic readings for a set of lines (the editor applies them as one edit)."""
        try:
            lines = [Line.model_validate(item) for item in body.lines]
        except ValueError as error:
            raise ProjectError(
                "送來的歌詞行不符合格式。", "The lines are not valid.", detail=str(error)
            ) from error
        if body.kind == "none":
            return {"lines": [clear_line(line).model_dump(mode="json") for line in lines]}
        taiwan = uses_taiwan_readings(body.language) or script_config(body.language) is None
        return {
            "lines": [
                annotate_line(line, body.kind, taiwan=taiwan).model_dump(mode="json")
                for line in lines
            ]
        }

    # ------------------------------------------------------------------------- media

    @app.get("/api/projects/{project_id}/media/{name}")
    def media_file(project_id: str, name: str) -> FileResponse:
        store = workspace.store(project_id)
        path = _media_path(store, store.load(), name)
        if path is None:
            raise ProjectNotFoundError(f"沒有這個媒體檔：{name}", f"No such media file: {name}")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)

    @app.get("/api/projects/{project_id}/thumbnail")
    def thumbnail(project_id: str) -> FileResponse:
        store = workspace.store(project_id)
        path = _thumbnail(store, store.load())
        if path is None:
            raise ProjectNotFoundError("這個專案沒有畫面。", "This project has no picture.")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/projects/{project_id}/peaks/{stem}")
    def peaks(project_id: str, stem: str) -> Response:
        store = workspace.store(project_id)
        path = _stem_path(store, stem)
        return Response(_peaks(store, stem, path), media_type="application/json")

    @app.get("/api/projects/{project_id}/analysis")
    def analysis(project_id: str) -> Response:
        store = workspace.store(project_id)
        path = store.paths.media / "analysis.json"
        if not path.is_file():
            return JSONResponse(
                {"onsets_ms": [], "regions_ms": [], "beats_ms": [], "tempo_bpm": None}
            )
        return Response(path.read_bytes(), media_type="application/json")

    @app.get("/api/projects/{project_id}/spectrogram/{stem}")
    def spectrogram(
        project_id: str,
        stem: str,
        start_ms: Annotated[int, Query(ge=0)],
        end_ms: Annotated[int, Query(gt=0)],
        width: Annotated[int, Query(ge=16, le=4096)] = 1024,
        height: Annotated[int, Query(ge=16, le=512)] = 128,
    ) -> Response:
        from karaforge.server.spectrogram import render_tile

        store = workspace.store(project_id)
        path = _stem_path(store, stem)
        if end_ms <= start_ms or end_ms - start_ms > 120_000:
            raise ProjectError("時間範圍不正確。", "Invalid time range.")
        png = render_tile(path, start_ms / 1000.0, end_ms / 1000.0, width, height)
        return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    # ----------------------------------------------------------------------- preview

    @app.get("/api/projects/{project_id}/preview.ass")
    def preview_ass(project_id: str) -> PlainTextResponse:
        store = workspace.store(project_id)
        return PlainTextResponse(_preview(project_id, store.load(), None)["ass"])

    @app.post("/api/projects/{project_id}/preview")
    def preview(project_id: str, body: PreviewBody) -> dict[str, Any]:
        store = workspace.store(project_id)
        if body.project is None:
            project = store.load()
        else:
            try:
                project = Project.model_validate(body.project)
            except ValueError as error:
                raise ProjectError(
                    "送來的專案內容不符合格式。",
                    "The submitted project is not valid.",
                    detail=str(error),
                ) from error
        return _preview(project_id, project, body.resolution)

    # -------------------------------------------------------------------------- jobs

    @app.post("/api/projects/{project_id}/jobs", status_code=202)
    def start_job(project_id: str, body: JobBody) -> dict[str, Any]:
        workspace.store(project_id)
        profile_for(body.profile, body.settings)  # validate before queueing
        job = jobs.submit(
            body.kind,
            project_id,
            {
                "profile": body.profile,
                "from_stage": body.from_stage,
                "lines": body.lines,
                "settings": body.settings,
            },
        )
        return {"job": job.to_dict()}

    @app.post("/api/projects/{project_id}/exports", status_code=202)
    def start_export(project_id: str, body: ExportBody) -> dict[str, Any]:
        from karaforge.exporting import get_format

        workspace.store(project_id)
        get_format(body.format)
        profile_for(body.profile)
        job = jobs.submit("export", project_id, body.model_dump())
        return {"job": job.to_dict()}

    @app.get("/api/projects/{project_id}/exports")
    def list_exports(project_id: str) -> dict[str, Any]:
        return {"exports": _export_files(project_id, workspace.store(project_id))}

    @app.get("/api/projects/{project_id}/exports/{name}")
    def download_export(project_id: str, name: str) -> FileResponse:
        path = _export_path(workspace.store(project_id), name)
        return FileResponse(path, filename=path.name)

    @app.delete("/api/projects/{project_id}/exports/{name}", status_code=204)
    def delete_export(project_id: str, name: str) -> Response:
        _export_path(workspace.store(project_id), name).unlink()
        return Response(status_code=204)

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": [job.to_dict() for job in jobs.list()]}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return {"job": _job(jobs, job_id).to_dict()}

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str) -> dict[str, Any]:
        _job(jobs, job_id)
        cancelled = jobs.cancel(job_id)
        assert cancelled is not None
        return {"job": cancelled.to_dict()}

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            yield "retry: 2000\n\n"
            active = [job.to_dict() for job in jobs.list() if job.state not in FINISHED]
            yield _sse({"type": "hello", "version": __version__, "jobs": active})
            iterator = bus.subscribe().__aiter__()
            pending: asyncio.Task[dict[str, Any]] | None = None
            try:
                while not await request.is_disconnected():
                    if pending is None:
                        pending = asyncio.ensure_future(anext(iterator))
                    done, _ = await asyncio.wait({pending}, timeout=_KEEP_ALIVE_S)
                    if done:
                        yield _sse(pending.result())
                        pending = None
                    else:
                        yield ": keep-alive\n\n"
            finally:
                if pending is not None:
                    pending.cancel()
                with contextlib.suppress(Exception):
                    await iterator.aclose()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]

        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    # ------------------------------------------------------------- themes and fonts

    @app.get("/api/themes")
    def themes() -> dict[str, Any]:
        return {"themes": _themes()}

    @app.put("/api/themes/{name}")
    def save_theme(name: str, body: dict[str, Any]) -> dict[str, Any]:
        return _save_theme(name, body)

    @app.delete("/api/themes/{name}", status_code=204)
    def delete_theme(name: str) -> Response:
        from karaforge import paths

        target = paths.user_themes_dir() / f"{name}.yaml"
        import re

        if not re.match(_THEME_NAME, name) or not target.is_file():
            raise ThemeError(f"沒有這個自訂主題：{name}", f"There is no user theme named '{name}'.")
        target.unlink()
        return Response(status_code=204)

    @app.get("/api/fonts")
    def fonts() -> dict[str, Any]:
        from karaforge.layout.fonts import default_library

        return {"fonts": [_font_entry(face.family, face.path) for face in default_library().faces]}

    @app.get("/api/fonts/{file}")
    def font_file(file: str) -> FileResponse:
        from karaforge.layout.fonts import default_library

        for face in default_library().faces:
            if face.path.name == file:
                return FileResponse(
                    face.path,
                    media_type="font/otf" if face.path.suffix.lower() == ".otf" else "font/ttf",
                    headers={"Cache-Control": "max-age=86400"},
                )
        raise ThemeError(f"找不到字型檔：{file}", f"Font file not found: {file}")

    # ------------------------------------------------------------------------ models

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        return {"models": _models()}

    @app.post("/api/models/download", status_code=202)
    def download_models(body: ModelsBody) -> dict[str, Any]:
        if body.profile is not None:
            get_profile(body.profile)
        job = jobs.submit("models", None, body.model_dump())
        return {"job": job.to_dict()}

    _mount_static(app, settings.static_dir)
    return app


# ------------------------------------------------------------------------------ helpers


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _job(jobs: JobManager, job_id: str) -> Job:
    job = jobs.get(job_id)
    if job is None:
        raise ProjectNotFoundError(f"找不到工作：{job_id}", f"Job not found: {job_id}")
    return job


def _media_path(store: ProjectStore, project: Project, name: str) -> Path | None:
    if name not in MEDIA_NAMES:
        return None
    relative = getattr(project.media, name)
    path = store.paths.resolve(relative)
    return path if path is not None and path.is_file() else None


def _media_urls(project_id: str, store: ProjectStore, project: Project) -> dict[str, str | None]:
    urls: dict[str, str | None] = {}
    for name in MEDIA_NAMES:
        path = _media_path(store, project, name)
        if path is None:
            urls[name] = None
        else:
            stamp = int(path.stat().st_mtime)
            urls[name] = f"/api/projects/{project_id}/media/{name}?v={stamp}"
    return urls


def _stem_path(store: ProjectStore, stem: str) -> Path:
    path = store.paths.media / f"{stem}.wav"
    if stem not in STEMS or not path.is_file():
        raise ProjectNotFoundError(
            f"這個專案還沒有「{stem}」音軌。", f"This project has no '{stem}' track yet."
        )
    return path


def _peaks(store: ProjectStore, stem: str, path: Path) -> bytes:
    """Waveform peaks of a stem as JSON, computed on first request and cached."""
    from karaforge.audio.io import read_wav
    from karaforge.audio.peaks import compute_peaks

    stat = path.stat()
    cached = store.paths.cache / "peaks" / f"{stem}-{stat.st_size}-{int(stat.st_mtime)}.json"
    if cached.is_file():
        return cached.read_bytes()
    data, rate = read_wav(path)
    payload = json.dumps(compute_peaks(data.mean(axis=1), rate), separators=(",", ":")).encode()
    cached.parent.mkdir(parents=True, exist_ok=True)
    for stale in cached.parent.glob(f"{stem}-*.json"):
        stale.unlink()
    cached.write_bytes(payload)
    return payload


def _thumbnail(store: ProjectStore, project: Project) -> Path | None:
    """A small still of the source video, made with ffmpeg on first request."""
    from karaforge.tools import ffmpeg

    source = _media_path(store, project, "source")
    if source is None or not project.media.has_video:
        return None
    target = store.paths.cache / "thumbnail.jpg"
    if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    at = max(0.0, project.meta.duration_ms / 1000.0 * 0.15)
    try:
        ffmpeg.run_ffmpeg(
            [
                "-ss",
                f"{at:.2f}",
                "-i",
                store.paths.relative(source),
                "-frames:v",
                "1",
                "-vf",
                "scale=480:-2",
                "-q:v",
                "5",
                store.paths.relative(target),
            ],
            cwd=store.root,
        )
    except (ffmpeg.FFmpegError, KaraForgeError):
        return None
    return target if target.is_file() else None


def _export_files(project_id: str, store: ProjectStore) -> list[dict[str, Any]]:
    folder = store.paths.exports
    if not folder.is_dir():
        return []
    files = [path for path in folder.iterdir() if path.is_file() and not path.name.endswith(".tmp")]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "modified_at": path.stat().st_mtime,
            "url": f"/api/projects/{project_id}/exports/{path.name}",
        }
        for path in files
    ]


def _export_path(store: ProjectStore, name: str) -> Path:
    path = (store.paths.exports / name).resolve()
    if path.parent != store.paths.exports.resolve() or not path.is_file():
        raise ProjectNotFoundError(f"找不到匯出檔：{name}", f"Export not found: {name}")
    return path


def _preview(
    project_id: str, project: Project, resolution: tuple[int, int] | None
) -> dict[str, Any]:
    """Lay out the project and write the ASS script the editor shows."""
    from karaforge.ass import render_ass
    from karaforge.layout.engine import build_plan
    from karaforge.layout.fonts import default_library

    del project_id
    if resolution is not None:
        project = project.model_copy(deep=True)
        project.render.resolution = resolution
    if not any(token.is_timed for line in project.lines for token in line.tokens):
        raise PipelineError(
            "歌詞還沒有時間，沒有東西可以預覽。",
            "The lyrics have no timing yet; there is nothing to preview.",
            hint_zh="請先處理這個專案，或用打點模式標記時間。",
            hint_en="Process the project first, or tap the timing in.",
        )
    plan = build_plan(project)
    library = default_library()
    used: list[dict[str, str]] = []
    for font in plan.fonts:
        face = library.find(font.family)
        used.append(_font_entry(face.family, face.path))
    return {
        "ass": render_ass(plan, title=project.meta.title),
        "fonts": used,
        "width": plan.width,
        "height": plan.height,
        "lines": len(plan.lines),
    }


def _font_entry(family: str, path: Path) -> dict[str, str]:
    return {"family": family, "file": path.name, "url": f"/api/fonts/{path.name}"}


def _themes() -> list[dict[str, Any]]:
    from karaforge import paths
    from karaforge.layout.theme import list_themes, load_theme

    bundled = paths.bundled_dir("themes")
    user = paths.user_themes_dir()
    result: list[dict[str, Any]] = []
    for name in list_themes():
        try:
            theme = load_theme(name)
        except ThemeError as error:
            result.append({"name": name, "builtin": False, "theme": None, "error": error.to_dict()})
            continue
        result.append(
            {
                "name": name,
                "builtin": (bundled / f"{name}.yaml").is_file()
                and not (user / f"{name}.yaml").is_file(),
                "theme": theme.model_dump(mode="json"),
                "error": None,
            }
        )
    return result


def _save_theme(name: str, body: dict[str, Any]) -> dict[str, Any]:
    import re

    from karaforge import paths
    from karaforge.layout.theme import Theme, dump_theme

    if not re.match(_THEME_NAME, name):
        raise ThemeError(
            "主題名稱只能用小寫英文字母、數字與連字號（最多 40 個字元）。",
            "Theme names may only use lower-case letters, digits and hyphens (at most 40).",
        )
    if (paths.bundled_dir("themes") / f"{name}.yaml").is_file():
        raise ThemeError(
            f"「{name}」是內建主題，請換一個名稱另存。",
            f"'{name}' is a built-in theme; save your version under another name.",
        )
    try:
        theme = Theme.model_validate({**body, "name": name})
    except ValueError as error:
        raise ThemeError(
            "主題內容不符合格式。", "The theme is not valid.", detail=str(error)
        ) from error
    folder = paths.user_themes_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.yaml").write_text(dump_theme(theme), encoding="utf-8")
    return {"name": name, "builtin": False, "theme": theme.model_dump(mode="json"), "error": None}


def _models() -> list[dict[str, Any]]:
    from karaforge.models import is_installed, load_registry

    return [
        {
            "id": spec.id,
            "kind": spec.kind,
            "title": spec.title,
            "license": spec.license,
            "commercial_use": spec.commercial_use,
            "bytes": spec.total_size,
            "installed": is_installed(spec),
            "note_zh": spec.note_zh,
            "note_en": spec.note_en,
        }
        for spec in load_registry().values()
    ]


def _download_models(
    params: dict[str, Any], progress: Callable[[float, str], None], job: Job
) -> dict[str, Any]:
    from karaforge.adapters.registry import describe_profile
    from karaforge.models import download, get_model, is_installed
    from karaforge.models.store import ENV_ACCEPT_LICENSES

    ids: list[Any] = list(params.get("ids") or [])
    wanted: list[str] = [str(item) for item in ids]
    if params.get("profile"):
        for info in describe_profile(get_profile(str(params["profile"]))):
            for model_id in info.models:
                wanted += [*get_model(model_id).requires, model_id]
    wanted = list(dict.fromkeys(wanted))
    specs = [get_model(model_id) for model_id in wanted]
    if params.get("accept_license"):
        # The same opt-in the command line uses for models that forbid commercial use.
        accepted = {item for item in os.environ.get(ENV_ACCEPT_LICENSES, "").split(",") if item}
        os.environ[ENV_ACCEPT_LICENSES] = ",".join(sorted(accepted | set(wanted)))
    missing = [spec for spec in specs if not is_installed(spec)]
    total = sum(spec.total_size for spec in missing) or 1
    done = 0
    for spec in missing:
        job.cancel.raise_if_cancelled()
        share = spec.total_size / total
        base = done / total

        download(spec, progress=_scaled(progress, base, share, spec.id), cancel=job.cancel)
        done += spec.total_size
    return {
        "downloaded": [spec.id for spec in missing],
        "already_installed": len(specs) - len(missing),
    }


def _scaled(
    progress: Callable[[float, str], None], base: float, share: float, label: str
) -> Callable[[float, str], None]:
    """A progress callback that maps ``0..1`` onto ``base..base + share`` of ``progress``."""

    def report(fraction: float, _message: str = "") -> None:
        progress(base + share * fraction, label)

    return report


@functools.lru_cache(maxsize=4)
def _ytdlp_version(executable: str, modified: float) -> str | None:
    """The version of a yt-dlp executable; remembered until the file changes (an update)."""
    from karaforge.tools import ytdlp

    del modified  # only part of the cache key
    try:
        return ytdlp.version(executable)
    except KaraForgeError:
        return None


def _system_info(settings: ServerSettings, workspace: Workspace) -> dict[str, Any]:
    from karaforge.adapters.registry import describe_profile, qwen_available, resolve_aligner
    from karaforge.device import resolve_device
    from karaforge.exporting import FORMATS
    from karaforge.models import get_model, is_installed
    from karaforge.tools import ffmpeg, ytdlp

    ffmpeg_info: dict[str, Any]
    try:
        capabilities = ffmpeg.capabilities()
        ffmpeg_info = {
            "found": True,
            "version": capabilities.version,
            "libass": capabilities.has_libass,
            "error": None,
        }
    except KaraForgeError as error:
        ffmpeg_info = {"found": False, "version": None, "libass": False, "error": error.to_dict()}

    ytdlp_info: dict[str, Any]
    try:
        executable = ytdlp.find_ytdlp()
        version = _ytdlp_version(executable, Path(executable).stat().st_mtime)
        ytdlp_info = {"found": True, "version": version}
    except (KaraForgeError, OSError):
        ytdlp_info = {"found": False, "version": None}

    profiles: list[dict[str, Any]] = []
    for name in profile_names():
        profile = get_profile(name)
        ids: list[str] = []
        for info in describe_profile(profile):
            for model_id in info.models:
                ids += [*get_model(model_id).requires, model_id]
        specs = [get_model(model_id) for model_id in dict.fromkeys(ids)]
        profiles.append(
            {
                "name": name,
                "asr_model": profile.asr.model,
                "aligner": resolve_aligner(profile.align.aligner),
                "models": [
                    {"id": spec.id, "bytes": spec.total_size, "installed": is_installed(spec)}
                    for spec in specs
                ],
            }
        )
    device = resolve_device(get_profile(settings.default_profile).device)
    return {
        "version": __version__,
        "workspace": str(workspace.root),
        "default_profile": settings.default_profile,
        "profiles": profiles,
        "device": {
            "kind": device.kind,
            "name": device.name,
            "fallback_reason_zh": device.fallback_reason_zh,
            "fallback_reason_en": device.fallback_reason_en,
        },
        "ffmpeg": ffmpeg_info,
        "ytdlp": ytdlp_info,
        "qwen": qwen_available(),
        "formats": [
            {
                "id": item.id,
                "suffix": item.suffix,
                "video": item.video,
                "title_zh": item.title_zh,
                "title_en": item.title_en,
            }
            for item in FORMATS.values()
        ],
    }


def _mount_static(app: FastAPI, static_dir: Path | None) -> None:
    """Serve the built single-page app; unknown paths fall back to ``index.html``."""
    if static_dir is None or not (static_dir / "index.html").is_file():

        @app.get("/")
        def no_frontend() -> PlainTextResponse:
            return PlainTextResponse(
                "KaraForge API is running, but the web app has not been built.\n"
                "Run `npm ci && npm run build` in web/ (or use the Docker image).\n"
            )

        return

    root = static_dir.resolve()

    @app.get("/{path:path}")
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message_en": "Not found"}}, 404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            headers = (
                {"Cache-Control": "max-age=31536000, immutable"}
                if "/assets/" in f"/{path}"
                else None
            )
            return FileResponse(candidate, headers=headers)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})


__all__ = ["ExportError", "ServerSettings", "create_app"]
