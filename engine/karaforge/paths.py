"""Filesystem locations used by KaraForge.

``KARAFORGE_HOME`` holds everything that is downloaded or installed per user (model weights,
optional tool binaries, user themes).  Bundled read-only resources (fonts, themes, the built
web app) ship inside the wheel under ``karaforge/_bundled`` and are read straight from the
repository when running from a source checkout.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir

ENV_HOME = "KARAFORGE_HOME"
ENV_WEB_DIST = "KARAFORGE_WEB_DIST"

BundledKind = Literal["fonts", "themes", "web"]

_PACKAGE_DIR = Path(__file__).resolve().parent


def home_dir() -> Path:
    """Return the per-user data directory (``$KARAFORGE_HOME`` or the platform default).

    The directory is not created; callers create the sub-directories they need.
    """
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir("karaforge", appauthor=False))


def models_dir() -> Path:
    """Directory that holds downloaded model weights."""
    return home_dir() / "models"


def bin_dir() -> Path:
    """Directory that is searched for tool binaries after ``PATH`` (e.g. a static ffmpeg)."""
    return home_dir() / "bin"


def user_themes_dir() -> Path:
    """Directory for themes saved by the user from the theme editor."""
    return home_dir() / "themes"


def repo_root() -> Path | None:
    """Return the source checkout root when running from one, otherwise ``None``."""
    candidate = _PACKAGE_DIR.parent.parent
    if (candidate / "pyproject.toml").is_file() and (candidate / "engine").is_dir():
        return candidate
    return None


def bundled_dir(kind: BundledKind) -> Path:
    """Locate a bundled resource directory.

    Lookup order: the packaged copy inside the wheel, then the source checkout.  For the web
    app the ``KARAFORGE_WEB_DIST`` environment variable takes precedence.

    Args:
        kind: Which resource to locate.

    Returns:
        The directory path.  It may not exist (e.g. the web app has not been built yet);
        callers are expected to check and report a helpful error.
    """
    if kind == "web":
        override = os.environ.get(ENV_WEB_DIST)
        if override:
            return Path(override).expanduser()
    packaged = _PACKAGE_DIR / "_bundled" / kind
    if packaged.is_dir():
        return packaged
    root = repo_root()
    if root is not None:
        return root / "web" / "dist" if kind == "web" else root / kind
    return packaged
