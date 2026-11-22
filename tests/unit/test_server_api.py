"""The HTTP API, exercised through FastAPI's test client with a hand-timed project.

No model and no ffmpeg is needed: the project gets its timing from the test, and the exports
used here are the text formats.
"""

from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from fastapi.testclient import TestClient

from karaforge.audio.io import write_wav
from karaforge.project import ProjectStore
from karaforge.server import ServerSettings, create_app
from karaforge.server.jobs import JobManager
from karaforge.server.workspace import Workspace, project_stats
from support import install_fake_ytdlp, song_project, timed_line


def tone(seconds: float = 3.0, rate: int = 16000) -> bytes:
    """A WAV file with a 440 Hz tone, as bytes."""
    import soundfile as sf

    time_axis = np.arange(round(seconds * rate)) / rate
    buffer = io.BytesIO()
    sf.write(buffer, (0.3 * np.sin(2 * np.pi * 440 * time_axis)).astype(np.float32), rate,
             format="WAV", subtype="PCM_16")  # fmt: skip
    return buffer.getvalue()


@dataclass
class Api:
    """The test client together with the server's own objects."""

    client: TestClient
    workspace: Workspace
    jobs: JobManager


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path / "home"))
    app = create_app(ServerSettings(workspace=tmp_path / "work"))
    with TestClient(app) as test_client:
        yield Api(
            test_client, cast(Workspace, app.state.workspace), cast(JobManager, app.state.jobs)
        )


@pytest.fixture
def client(api: Api) -> TestClient:
    return api.client


def make_project(api: Api, name: str = "demo") -> ProjectStore:
    """A ready-made project in the workspace: two timed lines and stand-in stems."""
    store = ProjectStore(api.workspace.folder(name))
    project = song_project(
        [
            timed_line("L001", "夜空裡的星星", 1_000, 300),
            timed_line("L002", "so bright", 3_200, 400),
        ],
        duration_ms=6_000,
    )
    project.media.audio = "media/audio.wav"
    project.media.vocals = "media/vocals.wav"
    store.create(project)
    samples = np.frombuffer(tone(6.0)[44:], dtype=np.int16).astype(np.float32) / 32768.0
    for stem in ("audio", "vocals"):
        write_wav(store.paths.media / f"{stem}.wav", samples, 16000)
    return store


def wait_job(client: TestClient, job_id: str, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        job: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()["job"]
        if job["state"] in ("done", "failed", "cancelled"):
            return job
        assert time.monotonic() < deadline, f"job still {job['state']}"
        time.sleep(0.05)


# ------------------------------------------------------------------------------ system


def test_health_and_system_information(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    info = client.get("/api/system").json()
    assert info["default_profile"] == "balanced"
    assert [profile["name"] for profile in info["profiles"]] == [
        "cpu-lite",
        "balanced",
        "gpu-quality",
    ]
    balanced = info["profiles"][1]
    assert balanced["aligner"] == "ctc"
    assert {model["id"] for model in balanced["models"]} >= {"whisper-small", "wav2vec2-zh"}
    assert {item["id"] for item in info["formats"]} >= {"mp4", "mkv", "lrc", "ultrastar"}
    assert info["device"]["kind"] in ("cpu", "cuda", "mps")
    assert isinstance(info["ffmpeg"]["found"], bool)
    assert "Run `npm ci" in client.get("/").text


# ---------------------------------------------------------------------------- projects


def test_project_life_cycle_through_upload_save_and_delete(client: TestClient) -> None:
    assert client.get("/api/projects").json() == {"projects": []}
    created = client.post(
        "/api/projects",
        files={"media": ("我的 歌.wav", tone(), "audio/wav")},
        data={
            "lyrics": "# title: 上傳的歌\n[女] 第一句\n第二句\n",
            "language": "zh-TW",
            "start": "false",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["job"] is None
    summary = body["project"]
    assert summary["id"] == "我的-歌" and summary["title"] == "上傳的歌"
    assert summary["stats"] == {
        "lines": 2, "tokens": 6, "timed_tokens": 0, "locked_tokens": 0, "low_confidence": 0,
    }  # fmt: skip
    assert summary["processed"] is False and summary["job"] is None

    listed = client.get("/api/projects").json()["projects"]
    assert [item["id"] for item in listed] == ["我的-歌"]
    detail = client.get("/api/projects/我的-歌").json()
    assert detail["project"]["lines"][0]["singer"] == "f"
    assert detail["media"]["source"].startswith("/api/projects/我的-歌/media/source?v=")
    assert detail["media"]["vocals"] is None and detail["exports"] == []

    # A second upload with the same name gets its own folder.
    again = client.post(
        "/api/projects",
        files={"media": ("我的 歌.wav", tone(), "audio/wav")},
        data={"start": "false"},
    )
    assert again.json()["project"]["id"] == "我的-歌-2"

    # Saving needs the revision the edit was based on.
    document = detail["project"]
    document["meta"]["artist"] = "新歌手"
    saved = client.put("/api/projects/我的-歌", json={"project": document, "revision": 0})
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    stale = client.put("/api/projects/我的-歌", json={"project": document, "revision": 0})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    assert "重新載入" in stale.json()["error"]["hint_zh"]
    broken = client.put("/api/projects/我的-歌", json={"project": {"lines": 5}, "revision": 1})
    assert broken.status_code == 400

    assert client.delete("/api/projects/我的-歌").status_code == 204
    assert client.get("/api/projects/我的-歌").status_code == 404
    assert [item["id"] for item in client.get("/api/projects").json()["projects"]] == ["我的-歌-2"]


def test_upload_rejects_unsupported_media_and_unknown_profiles(api: Api) -> None:
    client = api.client
    bad = client.post("/api/projects", files={"media": ("notes.docx", b"x", "application/x")})
    assert bad.status_code == 400
    assert "不支援" in bad.json()["error"]["message_zh"]
    unknown = client.post(
        "/api/projects", files={"media": ("a.wav", tone(), "audio/wav")}, data={"profile": "turbo"}
    )
    assert unknown.status_code == 400
    assert client.get("/api/projects").json() == {"projects": []}
    uploads = api.workspace.uploads
    assert not uploads.exists() or not any(uploads.iterdir())


def test_project_ids_cannot_escape_the_workspace(api: Api) -> None:
    client = api.client
    make_project(api)
    for bad in ("..", ".hidden", "a%2Fb", "%2E%2E%2Fdemo"):
        assert client.get(f"/api/projects/{bad}").status_code == 404
    assert client.get("/api/projects/missing").json()["error"]["code"] == "project_not_found"


def test_replacing_the_lyrics_accepts_any_supported_format(api: Api) -> None:
    client = api.client
    make_project(api)
    lrc = "[ti:換過的歌]\n[00:01.00]新的第一句\n[00:04.00]<00:04.00>逐<00:04.40>字<00:04.80>\n"
    response = client.put(
        "/api/projects/demo/lyrics", json={"text": lrc, "filename": "song.lrc", "revision": 0}
    )
    assert response.status_code == 200, response.text
    project = response.json()["project"]
    assert project["meta"]["title"] == "換過的歌"
    assert project["lines"][0]["time_hint"] == [1000, 4000]
    assert project["lines"][1]["tokens"][0]["start_ms"] == 4000
    conflict = client.put("/api/projects/demo/lyrics", json={"text": "一\n", "revision": 0})
    assert conflict.status_code == 409


def test_retokenize_keeps_the_times_of_unchanged_tokens(client: TestClient) -> None:
    line = timed_line("L001", "我愛你", 3_000, 600).model_dump(mode="json")
    response = client.post("/api/tools/retokenize", json={"line": line, "text": "我喜歡你"})
    tokens = response.json()["line"]["tokens"]
    assert [(t["text"], t["start_ms"]) for t in tokens] == [
        ("我", 3000), ("喜", 3600), ("歡", 3900), ("你", 4200),
    ]  # fmt: skip
    assert (
        client.post("/api/tools/retokenize", json={"line": {"id": ""}, "text": "x"}).status_code
        == 400
    )


# ------------------------------------------------------------------------------- media


def test_media_supports_range_requests(api: Api) -> None:
    client = api.client
    make_project(api)
    whole = client.get("/api/projects/demo/media/vocals")
    assert whole.status_code == 200 and whole.headers["content-type"].startswith("audio/")
    assert whole.headers.get("accept-ranges") == "bytes"
    part = client.get("/api/projects/demo/media/vocals", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.content == whole.content[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(whole.content)}"
    assert client.get("/api/projects/demo/media/instrumental").status_code == 404
    assert client.get("/api/projects/demo/media/project.json").status_code == 404
    assert client.get("/api/projects/demo/thumbnail").status_code == 404  # no video


def test_peaks_analysis_and_spectrogram(api: Api) -> None:
    client = api.client
    store = make_project(api)
    peaks = client.get("/api/projects/demo/peaks/vocals").json()
    assert peaks["sample_rate"] == 16000 and peaks["length"] == 96000
    assert len(peaks["levels"][0]["max"]) == 375  # 96000 / 256
    assert max(peaks["levels"][0]["max"]) == pytest.approx(38, abs=2)  # 0.3 * 127
    cached = list((store.paths.cache / "peaks").glob("vocals-*.json"))
    assert len(cached) == 1
    assert client.get("/api/projects/demo/peaks/vocals").content == cached[0].read_bytes()
    assert client.get("/api/projects/demo/peaks/drums").status_code == 404

    assert client.get("/api/projects/demo/analysis").json()["onsets_ms"] == []
    (store.paths.media / "analysis.json").write_text('{"onsets_ms": [1000, 1300]}')
    assert client.get("/api/projects/demo/analysis").json() == {"onsets_ms": [1000, 1300]}

    image = client.get(
        "/api/projects/demo/spectrogram/vocals",
        params={"start_ms": 1000, "end_ms": 3000, "width": 200, "height": 64},
    )
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(image.content[16:20], "big") == 200  # width in the IHDR chunk
    assert int.from_bytes(image.content[20:24], "big") == 64
    too_long = client.get(
        "/api/projects/demo/spectrogram/vocals", params={"start_ms": 0, "end_ms": 500_000}
    )
    assert too_long.status_code == 400


# ----------------------------------------------------------------------------- preview


def test_preview_renders_the_saved_project_or_an_unsaved_draft(api: Api) -> None:
    client = api.client
    make_project(api)
    saved = client.get("/api/projects/demo/preview.ass")
    assert saved.status_code == 200 and "[V4+ Styles]" in saved.text
    assert "PlayResX: 1920" in saved.text

    document = client.get("/api/projects/demo").json()["project"]
    document["lines"][0]["tokens"][0]["start_ms"] = 500
    draft = client.post(
        "/api/projects/demo/preview", json={"project": document, "resolution": [1280, 720]}
    ).json()
    assert draft["width"] == 1280 and draft["lines"] == 2
    assert "PlayResX: 1280" in draft["ass"] and draft["ass"] != saved.text
    assert draft["fonts"] == [
        {
            "family": "GenSenRounded2 TW B",
            "file": "GenSenRounded2TW-B.otf",
            "url": "/api/fonts/GenSenRounded2TW-B.otf",
        }
    ]
    # The draft was not saved.
    assert client.get("/api/projects/demo").json()["summary"]["revision"] == 0

    for line in document["lines"]:
        for token in line["tokens"]:
            token["start_ms"] = token["end_ms"] = None
    untimed = client.post("/api/projects/demo/preview", json={"project": document})
    assert untimed.status_code == 400
    assert "預覽" in untimed.json()["error"]["message_zh"]
    assert client.post("/api/projects/demo/preview", json={"project": {"x": 1}}).status_code == 400


# -------------------------------------------------------------------------------- jobs


def test_export_job_writes_a_file_that_can_be_listed_downloaded_and_deleted(api: Api) -> None:
    client = api.client
    make_project(api)
    started = client.post("/api/projects/demo/exports", json={"format": "elrc"})
    assert started.status_code == 202
    job = wait_job(client, started.json()["job"]["id"])
    assert job["state"] == "done", job
    assert job["result"]["file"] == "測試歌曲.enhanced.lrc"
    exports = client.get("/api/projects/demo/exports").json()["exports"]
    assert [item["name"] for item in exports] == ["測試歌曲.enhanced.lrc"]
    downloaded = client.get(exports[0]["url"])
    assert "<00:01.00>夜<00:01.30>空" in downloaded.text
    assert "attachment" in downloaded.headers["content-disposition"]

    archive = wait_job(
        client,
        client.post("/api/projects/demo/exports", json={"format": "kfproj"}).json()["job"]["id"],
    )
    assert archive["state"] == "done"
    packed = client.get("/api/projects/demo/exports/測試歌曲.kfproj.zip")
    with zipfile.ZipFile(io.BytesIO(packed.content)) as bundle:
        assert "demo.kfproj/project.json" in bundle.namelist()

    assert client.delete("/api/projects/demo/exports/測試歌曲.enhanced.lrc").status_code == 204
    assert client.get("/api/projects/demo/exports/測試歌曲.enhanced.lrc").status_code == 404
    assert client.get("/api/projects/demo/exports/..%2Fproject.json").status_code == 404
    assert len(client.get("/api/jobs").json()["jobs"]) == 2


def test_failing_jobs_explain_themselves_and_bad_requests_are_refused(api: Api) -> None:
    client = api.client
    make_project(api)
    # A video export needs the accompaniment stem, which this project does not have.
    job = wait_job(
        client,
        client.post("/api/projects/demo/exports", json={"format": "mp4"}).json()["job"]["id"],
    )
    assert job["state"] == "failed"
    assert job["error"]["message_zh"] and job["error"]["message_en"]
    summary = client.get("/api/projects/demo").json()["summary"]
    assert summary["job"] is None and summary["last_job"]["state"] == "failed"

    assert client.post("/api/projects/demo/exports", json={"format": "avi"}).status_code == 400
    assert client.post("/api/projects/demo/jobs", json={"profile": "turbo"}).status_code == 400
    bad_setting = client.post("/api/projects/demo/jobs", json={"settings": {"align.nope": 1}})
    assert bad_setting.status_code == 400
    assert client.post("/api/projects/missing/jobs", json={}).status_code == 404
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.delete("/api/jobs/nope").status_code == 404


def test_a_project_with_a_running_job_cannot_be_deleted(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    import karaforge.exporting as exporting

    client = api.client
    make_project(api)
    gate = threading.Event()
    real_export = exporting.export

    def slow_export(*args: Any, **kwargs: Any) -> Path:
        while not gate.is_set():
            kwargs["cancel"].raise_if_cancelled()
            time.sleep(0.01)
        return real_export(*args, **kwargs)

    monkeypatch.setattr(exporting, "export", slow_export)
    running = client.post("/api/projects/demo/exports", json={"format": "lrc"}).json()["job"]
    waiting = client.post("/api/projects/demo/exports", json={"format": "srt"}).json()["job"]
    deadline = time.monotonic() + 5
    while client.get(f"/api/jobs/{running['id']}").json()["job"]["state"] != "running":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    summary = client.get("/api/projects/demo").json()["summary"]
    assert summary["job"]["id"] == running["id"]

    refused = client.delete("/api/projects/demo")
    assert refused.status_code == 400 and "取消" in refused.json()["error"]["message_zh"]
    # The waiting job is cancelled at once, the running one at its next check.
    assert client.delete(f"/api/jobs/{waiting['id']}").json()["job"]["state"] == "cancelled"
    client.delete(f"/api/jobs/{running['id']}")
    assert wait_job(client, running["id"])["state"] == "cancelled"
    assert client.get("/api/projects/demo/exports").json()["exports"] == []
    assert client.delete("/api/projects/demo").status_code == 204


# ------------------------------------------------------------------------ video links

LINK = "https://youtu.be/abc123"


@pytest.fixture
def fake_ytdlp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the stand-in for yt-dlp; it "downloads" a short tone."""
    media = tmp_path / "downloaded.wav"
    media.write_bytes(tone())
    for name, value in install_fake_ytdlp(tmp_path / "bin", media=media).items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("FAKE_YTDLP_MODE", raising=False)


def test_a_video_link_is_described_before_anything_is_downloaded(
    client: TestClient, fake_ytdlp: None
) -> None:
    assert client.get("/api/system").json()["ytdlp"] == {"found": True, "version": "2099.01.01"}
    described = client.post("/api/media/probe", json={"url": LINK})
    assert described.status_code == 200, described.text
    media = described.json()["media"]
    assert (media["title"], media["artist"]) == ("晴天 (Official MV)", "某歌手")
    assert media["url"] == "https://www.youtube.com/watch?v=abc123"
    assert media["duration_ms"] == 269_500 and media["has_video"] is True
    refused = client.post("/api/media/probe", json={"url": "not a link"})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "download_failed"


def test_a_project_is_made_from_a_video_link(
    api: Api, fake_ytdlp: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import karaforge.stages.standard as standard

    client = api.client
    accepted = client.post(
        "/api/projects/import",
        data={
            "url": LINK,
            "title": "晴天",
            "lyrics": "[女] 第一句\n第二句\n",
            "language": "zh-TW",
            "start": "false",
        },
    )
    assert accepted.status_code == 202, accepted.text
    job = accepted.json()["job"]
    assert (job["kind"], job["project_id"], job["params"]["url"]) == ("import", None, LINK)
    finished = wait_job(client, job["id"])
    assert finished["state"] == "done", finished
    assert finished["result"] == {"project_id": "晴天", "job": None}
    project = client.get("/api/projects/晴天").json()["project"]
    # The title typed in the wizard wins; the artist comes from the video.
    assert (project["meta"]["title"], project["meta"]["artist"]) == ("晴天", "某歌手")
    assert project["lines"][0]["singer"] == "f" and project["media"]["source"] == "media/source.wav"
    assert not any(api.workspace.uploads.iterdir())

    # Without a title the video's own is used; with start, processing is queued at once.
    processed: list[str] = []

    def fake_pipeline(store: ProjectStore, **_options: Any) -> Any:
        processed.append(store.root.name)
        return type("Report", (), {"executed": ["ingest"], "cached": []})()

    monkeypatch.setattr(standard, "run_pipeline", fake_pipeline)
    started = client.post("/api/projects/import", data={"url": LINK, "profile": "cpu-lite"})
    finished = wait_job(client, started.json()["job"]["id"])
    project_id = finished["result"]["project_id"]
    assert client.get(f"/api/projects/{project_id}").json()["project"]["meta"]["title"] == (
        "晴天 (Official MV)"
    )
    process = wait_job(client, finished["result"]["job"])
    assert (process["kind"], process["project_id"], process["state"]) == (
        "process", project_id, "done",
    )  # fmt: skip
    assert process["params"]["profile"] == "cpu-lite"
    assert processed == [f"{project_id}.kfproj"]


def test_link_imports_are_refused_before_anything_is_downloaded(
    api: Api, fake_ytdlp: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = api.client
    for data in ({"url": "youtube.com/watch?v=abc"}, {"url": LINK, "profile": "turbo"}):
        assert client.post("/api/projects/import", data=data).status_code == 400, data
    unreadable = client.post(
        "/api/projects/import",
        data={"url": LINK},
        files={"lyrics_file": ("notes.docx", b"x", "application/octet-stream")},
    )
    assert unreadable.status_code == 400
    monkeypatch.setenv("KARAFORGE_YTDLP", "/nowhere/yt-dlp")
    missing = client.post("/api/projects/import", data={"url": LINK})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "tool_missing"
    assert client.get("/api/system").json()["ytdlp"] == {"found": False, "version": None}
    assert api.jobs.list() == []
    uploads = api.workspace.uploads
    assert not uploads.exists() or not any(uploads.iterdir())


def test_a_failed_download_explains_itself_and_leaves_nothing_behind(
    api: Api, fake_ytdlp: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_YTDLP_MODE", "error")
    client = api.client
    job = client.post("/api/projects/import", data={"url": LINK, "lyrics": "一句"}).json()["job"]
    failed = wait_job(client, job["id"])
    assert failed["state"] == "failed"
    assert failed["error"]["message_zh"] == "無法下載這部影片：Video unavailable"
    assert "yt-dlp -U" in failed["error"]["hint_zh"]
    assert client.get("/api/projects").json() == {"projects": []}
    assert not any(api.workspace.uploads.iterdir())


# ------------------------------------------------------------------- themes and fonts


def test_themes_can_be_listed_saved_and_deleted(client: TestClient) -> None:
    themes = {item["name"]: item for item in client.get("/api/themes").json()["themes"]}
    assert set(themes) >= {"classic-ktv", "pop-round", "clean-center", "zhuyin-learner"}
    assert all(item["builtin"] for item in themes.values())
    mine = themes["classic-ktv"]["theme"]
    mine["font"]["size"] = 96
    saved = client.put("/api/themes/my-big-theme", json=mine)
    assert saved.status_code == 200, saved.text
    assert saved.json()["theme"]["name"] == "my-big-theme" and saved.json()["builtin"] is False
    listed = {item["name"]: item for item in client.get("/api/themes").json()["themes"]}
    assert listed["my-big-theme"]["theme"]["font"]["size"] == 96

    assert client.put("/api/themes/classic-ktv", json=mine).status_code == 400
    assert client.put("/api/themes/Bad Name!", json=mine).status_code == 400
    wrong = client.put("/api/themes/broken", json={"font": {"size": "huge"}})
    assert wrong.status_code == 400 and "detail" in wrong.json()["error"]
    assert client.delete("/api/themes/my-big-theme").status_code == 204
    assert client.delete("/api/themes/my-big-theme").status_code == 400
    assert client.delete("/api/themes/classic-ktv").status_code == 400


def test_fonts_are_listed_and_served(client: TestClient) -> None:
    fonts = client.get("/api/fonts").json()["fonts"]
    families = {font["family"] for font in fonts}
    assert {"GenSenRounded2 TW B", "Noto Sans TC"} <= families
    font = client.get(fonts[0]["url"])
    assert font.status_code == 200 and len(font.content) > 100_000
    assert font.headers["content-type"] in ("font/otf", "font/ttf")
    assert client.get("/api/fonts/nope.otf").status_code == 400


def test_models_are_listed_with_their_licences(client: TestClient) -> None:
    models = {item["id"]: item for item in client.get("/api/models").json()["models"]}
    assert models["mms-fa"]["commercial_use"] is False
    assert models["wav2vec2-zh"]["license"] == "Apache-2.0"
    assert all(isinstance(item["installed"], bool) for item in models.values())
    assert client.post("/api/models/download", json={"profile": "turbo"}).status_code == 400
    # Nothing to do: the job finishes at once.
    job = wait_job(client, client.post("/api/models/download", json={}).json()["job"]["id"])
    assert job["state"] == "done" and job["result"] == {"downloaded": [], "already_installed": 0}


# ------------------------------------------------------------------------- web app


def test_built_web_app_is_served_with_a_fallback_to_index(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>KaraForge</title>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("secret")
    app = create_app(ServerSettings(workspace=tmp_path / "work", static_dir=static))
    with TestClient(app) as web:
        assert "KaraForge" in web.get("/").text
        script = web.get("/assets/app.js")
        assert script.text == "console.log(1)" and "immutable" in script.headers["cache-control"]
        # Client-side routes get the app shell; nothing outside the folder is reachable.
        assert "KaraForge" in web.get("/projects/demo/edit").text
        assert "secret" not in web.get("/..%2Fsecret.txt").text
        assert web.get("/api/nope").status_code == 404
        assert web.get("/api/health").json()["status"] == "ok"


def test_project_stats_count_timed_locked_and_doubtful_tokens() -> None:
    project = song_project([timed_line("L001", "一二三四", 0, 300)])
    tokens = project.lines[0].tokens
    tokens[0] = tokens[0].model_copy(update={"confidence": 0.2})
    tokens[1] = tokens[1].model_copy(update={"confidence": 0.2, "locked": True})
    tokens[2] = tokens[2].retimed(None, None)
    stats = project_stats(project)
    assert (stats.lines, stats.tokens, stats.timed_tokens) == (1, 4, 3)
    assert (stats.locked_tokens, stats.low_confidence) == (1, 1)
    assert json.dumps(stats.__dict__)


def test_readings_tool_annotates_switches_and_clears(client: TestClient) -> None:
    lines = [
        {
            "id": "L001",
            "tokens": [
                {"text": "寂"},
                {"text": "寞"},
                {"text": "的 "},
                {"text": "night"},
                {"text": "行", "ruby": "ㄏㄤˊ", "ruby_source": "manual"},
            ],
        }
    ]

    def rubies(payload: dict[str, Any]) -> list[tuple[str | None, str | None]]:
        return [(token["ruby"], token["ruby_source"]) for token in payload["lines"][0]["tokens"]]

    zhuyin = client.post("/api/tools/ruby", json={"lines": lines, "kind": "zhuyin"}).json()
    assert rubies(zhuyin) == [
        ("ㄐㄧˊ", "auto"),
        ("ㄇㄛˋ", "auto"),
        ("˙ㄉㄜ", "auto"),
        (None, None),
        ("ㄏㄤˊ", "manual"),
    ]
    mainland = client.post(
        "/api/tools/ruby", json={"lines": zhuyin["lines"], "kind": "pinyin", "language": "zh-CN"}
    ).json()
    assert rubies(mainland)[:3] == [("jì", "auto"), ("mò", "auto"), ("de", "auto")]
    assert rubies(mainland)[4] == ("ㄏㄤˊ", "manual")
    cleared = client.post("/api/tools/ruby", json={"lines": mainland["lines"], "kind": "none"})
    assert rubies(cleared.json()) == [(None, None)] * 4 + [("ㄏㄤˊ", "manual")]

    assert client.post("/api/tools/ruby", json={"lines": [{"id": ""}]}).status_code == 400
    assert client.post("/api/tools/ruby", json={"lines": lines, "kind": "kana"}).status_code == 422


def test_lyrics_get_readings_when_they_enter_a_project(api: Api) -> None:
    store = make_project(api)
    revision = store.current_revision()
    response = api.client.put(
        "/api/projects/demo/lyrics",
        json={"text": "我們去銀行\nhello 世界", "filename": "lyrics.txt", "revision": revision},
    )
    assert response.status_code == 200, response.text
    project = store.load()
    assert [token.ruby for token in project.lines[0].tokens] == [
        "ㄨㄛˇ",
        "˙ㄇㄣ",
        "ㄑㄩˋ",
        "ㄧㄣˊ",
        "ㄏㄤˊ",
    ]
    assert [token.ruby for token in project.lines[1].tokens] == [None, "ㄕˋ", "ㄐㄧㄝˋ"]

    # An edited line keeps its readings up to date; the language picks the regional reading.
    line = project.lines[0].model_dump(mode="json")
    edited = api.client.post(
        "/api/tools/retokenize", json={"line": line, "text": "我們去旅行", "language": "zh-TW"}
    ).json()["line"]
    assert [token["ruby"] for token in edited["tokens"]][3:] == ["ㄌㄩˇ", "ㄒㄧㄥˊ"]
