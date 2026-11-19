"""Language selection for CLI and server messages."""

from __future__ import annotations

import os

from karaforge.errors import Lang

ENV_LANG = "KARAFORGE_LANG"


def current_lang() -> Lang:
    """Return the UI language: ``KARAFORGE_LANG`` (``zh``/``en``), default Traditional Chinese."""
    value = os.environ.get(ENV_LANG, "zh").strip().lower()
    return "en" if value.startswith("en") else "zh"


def pick(zh: str, en: str, lang: Lang | None = None) -> str:
    """Choose between a Chinese and an English string for the active language."""
    return zh if (lang or current_lang()) == "zh" else en
