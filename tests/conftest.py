"""Shared pytest fixtures and markers."""

from __future__ import annotations

import os
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


TEST_PROFILE = "cpu-lite"
"""Profile used by the tests that run real models."""


def _missing_models() -> list[str]:
    """Models of the test profile that have not been downloaded."""
    from karaforge.cli import profile_model_ids
    from karaforge.models import get_model, is_installed
    from karaforge.pipeline import get_profile

    try:
        return [
            model_id
            for model_id in profile_model_ids(get_profile(TEST_PROFILE))
            if not is_installed(get_model(model_id))
        ]
    except ImportError as exc:  # an ML dependency is not installed
        return [f"dependency missing: {exc.name}"]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests whose external requirements are not met on this machine."""
    have_ffmpeg: bool | None = None
    missing_models: list[str] | None = None
    for item in items:
        needs_models = "models" in item.keywords
        if "ffmpeg" in item.keywords or "visual" in item.keywords or needs_models:
            if have_ffmpeg is None:
                have_ffmpeg = _ffmpeg_available()
            if not have_ffmpeg:
                item.add_marker(pytest.mark.skip(reason="ffmpeg with libass is not available"))
                continue
        if needs_models:
            if missing_models is None:
                missing_models = _missing_models()
            if missing_models:
                item.add_marker(
                    pytest.mark.skip(
                        reason="model weights not downloaded ("
                        + ", ".join(missing_models)
                        + f"); run: kf models download --profile {TEST_PROFILE}"
                    )
                )


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


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> GoldenChecker:
    """Compare text with a file under ``tests/golden`` (see :class:`GoldenChecker`)."""
    return GoldenChecker()


class GoldenChecker:
    """Golden-file comparison.

    ``check(name, text)`` fails when ``text`` differs from ``tests/golden/<name>``.  Run pytest
    with ``KARAFORGE_UPDATE_GOLDEN=1`` to (re)write the files after an intended change, and
    review the diff before committing.
    """

    directory = REPO_ROOT / "tests" / "golden"

    def check(self, name: str, text: str) -> None:
        """Assert that ``text`` equals the stored golden file ``name``."""
        path = self.directory / name
        if os.environ.get("KARAFORGE_UPDATE_GOLDEN") == "1":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return
        if not path.is_file():
            pytest.fail(f"golden file {path} is missing; run with KARAFORGE_UPDATE_GOLDEN=1")
        expected = path.read_text(encoding="utf-8")
        assert text == expected, f"output differs from golden file {name}"
