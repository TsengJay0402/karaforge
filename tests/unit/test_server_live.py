"""Things that need a real socket: the event stream and ``kf serve`` itself."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from karaforge.project import ProjectStore
from karaforge.server import ServerSettings, create_app
from support import song_project, timed_line


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A server on a random local port with one hand-timed project; yields its base URL."""
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path / "home"))
    workspace = tmp_path / "work"
    store = ProjectStore(workspace / "demo.kfproj")
    store.create(song_project([timed_line("L001", "一二三", 1_000, 300)], duration_ms=4_000))
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(ServerSettings(workspace=workspace)), port=port, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while True:
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            assert time.monotonic() < deadline, "server did not start"
            time.sleep(0.05)
    yield base
    server.should_exit = True
    thread.join(timeout=10)


def next_event(lines: Iterator[str]) -> dict[str, Any]:
    """The next ``data:`` event of an open event stream."""
    for line in lines:
        if line.startswith("data: "):
            event: dict[str, Any] = json.loads(line[len("data: ") :])
            return event
    raise AssertionError("the event stream ended")


def test_event_stream_reports_jobs_and_saved_projects(live: str) -> None:
    with (
        httpx.Client(base_url=live, timeout=10) as client,
        client.stream("GET", "/api/events") as stream,
    ):
        assert stream.headers["content-type"].startswith("text/event-stream")
        lines = stream.iter_lines()
        hello = next_event(lines)
        assert hello["type"] == "hello" and hello["jobs"] == []

        # Saving from "another window" is announced to everyone who listens.
        document = client.get("/api/projects/demo").json()["project"]
        document["meta"]["artist"] = "新歌手"
        client.put("/api/projects/demo", json={"project": document, "revision": 0})
        saved = next_event(lines)
        assert saved == {"type": "project", "id": "demo", "revision": 1, "reason": "saved"}

        # A job announces every state it goes through, then the project it touched.
        started = client.post("/api/projects/demo/exports", json={"format": "lrc"}).json()
        job_id = started["job"]["id"]
        states: list[str] = []
        project_events: list[dict[str, Any]] = []
        while "done" not in states or not project_events:
            event = next_event(lines)
            if event["type"] == "job" and event["job"]["id"] == job_id:
                states.append(event["job"]["state"])
            elif event["type"] == "project":
                project_events.append(event)
        assert states[0] == "queued" and states[-1] == "done" and "running" in states
        assert project_events[0]["reason"] == "job"

    # A second listener that connects while nothing happens still gets its greeting.
    with (
        httpx.Client(base_url=live, timeout=10) as client,
        client.stream("GET", "/api/events") as stream,
    ):
        assert next_event(stream.iter_lines())["type"] == "hello"


def test_media_range_requests_over_a_real_connection(live: str, tmp_path: Path) -> None:
    media = tmp_path / "work" / "demo.kfproj" / "media" / "source.wav"
    media.write_bytes(bytes(range(256)) * 40)
    store = ProjectStore(tmp_path / "work" / "demo.kfproj")
    project = store.load()
    project.media.source = "media/source.wav"
    store.save(project)
    response = httpx.get(
        f"{live}/api/projects/demo/media/source", headers={"Range": "bytes=256-511"}, timeout=10
    )
    assert response.status_code == 206
    assert response.content == bytes(range(256))
