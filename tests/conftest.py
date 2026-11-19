"""Shared pytest fixtures and markers."""

from __future__ import annotations

from pathlib import Path

import pytest

from karaforge.errors import ToolMissingError
from karaforge.tools import ffmpeg

REPO_ROOT = Path(__file__).resolve().parent.parent


def _ffmpeg_available() -> bool:
    try:
        return ffmpeg.capabilities().has_libass
    except (ToolMissingError, ffmpeg.FFmpegError):
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests whose external requirements are not met on this machine."""
    have_ffmpeg: bool | None = None
    for item in items:
        if "ffmpeg" in item.keywords or "visual" in item.keywords:
            if have_ffmpeg is None:
                have_ffmpeg = _ffmpeg_available()
            if not have_ffmpeg:
                item.add_marker(pytest.mark.skip(reason="ffmpeg with libass is not available"))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Root of the source checkout."""
    return REPO_ROOT


@pytest.fixture
def work_dir(tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest) -> Path:
    """A scratch directory inside the repository.

    Tests that call ffmpeg use this instead of ``tmp_path`` so that a containerised ffmpeg
    (see ``docker/ffmpeg-wrapper``) can reach the files without mounting the system temp dir.
    """
    base = REPO_ROOT / ".pytest_tmp"
    base.mkdir(exist_ok=True)
    name = "".join(c if c.isalnum() else "_" for c in request.node.name)[:60]
    path = base / name
    if path.exists():
        import shutil

        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path
