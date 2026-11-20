"""Script conversion for recognised Chinese text (Simplified ↔ Traditional).

Speech recognisers write Chinese in whatever script their training data favoured —
Whisper mostly answers in Simplified.  A lyric draft has to be in the script of the project
language, so recognised text is converted character by character.  Only the *script* is
changed: the phrase-level OpenCC tables that also swap vocabulary (``软件`` → ``軟體``) are
deliberately not used, because a draft must keep the words that were sung.
"""

from __future__ import annotations

from functools import lru_cache

from opencc import OpenCC

_SIMPLIFIED_REGIONS = frozenset({"cn", "sg", "my", "hans"})
_HONG_KONG_REGIONS = frozenset({"hk", "mo"})
_CHINESE = frozenset({"zh", "cmn", "yue", "nan", "hak"})


def script_config(language: str) -> str | None:
    """Name of the OpenCC conversion that yields the script of ``language``.

    ``zh-TW`` (and plain ``zh``: Traditional is this project's default) → ``s2tw``,
    ``zh-HK`` → ``s2hk``, ``zh-CN`` / ``zh-Hans`` → ``t2s``; ``None`` for languages that are
    not Chinese.
    """
    parts = [part for part in language.strip().lower().replace("_", "-").split("-") if part]
    if not parts or parts[0] not in _CHINESE:
        return None
    rest = set(parts[1:])
    if rest & _SIMPLIFIED_REGIONS:
        return "t2s"
    if rest & _HONG_KONG_REGIONS:
        return "s2hk"
    return "s2tw"


@lru_cache(maxsize=4)
def _converter(config: str) -> OpenCC:
    return OpenCC(config)


def convert_script(text: str, language: str) -> str:
    """Write ``text`` in the script of ``language`` (unchanged for non-Chinese languages)."""
    config = script_config(language)
    if config is None or not text:
        return text
    return _converter(config).convert(text)
