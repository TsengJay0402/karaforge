"""Parser for the plain-text lyrics format (see ``docs/lyrics-format.md``).

Example::

    # title: 歌名
    # artist: 歌手

    [男] 第一句歌詞
    [女] 第二句歌詞
    [合] 一起唱 together

    這句沒有標記,沿用上一句的演唱者
    他還是重{ㄔㄨㄥˊ}複了一次
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from pathlib import Path

from karaforge.errors import LyricsFormatError
from karaforge.project.schema import Line, Meta, Singer, Token, default_singers
from karaforge.text.tokenize import tokenize

_META_KEYS = {
    "title": "title",
    "歌名": "title",
    "曲名": "title",
    "artist": "artist",
    "歌手": "artist",
    "演唱": "artist",
    "lyricist": "lyricist",
    "作詞": "lyricist",
    "作词": "lyricist",
    "composer": "composer",
    "作曲": "composer",
    "language": "language",
    "lang": "language",
    "語言": "language",
}
_SINGER_ALIASES = {
    "男": "m",
    "m": "m",
    "male": "m",
    "女": "f",
    "f": "f",
    "female": "f",
    "合": "all",
    "合唱": "all",
    "all": "all",
    "duet": "all",
    "both": "all",
}
_FALLBACK_SLOTS = ("male", "female", "duet")
_META_LINE = re.compile(r"^#\s*([^:：]+?)\s*[:：]\s*(.*)$")
_TAG = re.compile(r"^\[([^\[\]]{1,32})\]\s*")
# LRC leftovers that people paste into .txt files: they carry no meaning here (use the .lrc
# importer to keep the times), so they are removed instead of ending up as lyric text.
_LEADING_TIME_TAGS = re.compile(r"^(?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]\s*)+")
_INLINE_TIME_TAGS = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")
_LRC_ID_TAG = re.compile(r"^\[(ti|ar|al|au|by|re|ve|la|length|offset|tool)\s*:(.*)\]$", re.I)
_LRC_ID_KEYS = {"ti": "title", "ar": "artist", "au": "composer"}

# Frequent characters (Traditional and Simplified) used to tell Big5 from GB18030 when a
# file is in neither UTF-8 nor UTF-16: the decoding that yields more of them wins.
_COMMON_HANZI = frozenset(
    "的一是不了人我在有他這个們中來上大為和國地到以說時要就出會可也你對生能而子那得於著下自之年過"
    "發後作裡用道行所然家種事成方多經麼去法學如都同現當沒動面起看定天分還進好小部其些主樣理心她"
    "本前開但因只從想實日者意無力它與長把機十民第公此已工使情明性知全三又關點正業外將兩高間由問"
    "很最重並物手應向頭文體相見被什二等或新己身果加月話合回特代內信表化老給世位次門常先海通兒原"
    "東聲提立及比解水名真處走各入幾口認平氣題活更別打女變四神總何電數安少報才結反受目太再感做"
    "这个们来为国说时会对过发后里种经么学现当没动还进开从实无与长机关点业将两间问并应头体见给"
    "变总电数报结气题别爱风花雪月夜星光夢梦歌唱聽听淚泪雨海山路遠远笑哭想念記记憶忆離离開愛誰谁"
)


@dataclass
class ParsedLyrics:
    """Result of parsing a lyrics file."""

    meta: dict[str, str] = field(default_factory=dict[str, str])
    singers: list[Singer] = field(default_factory=default_singers)
    lines: list[Line] = field(default_factory=list[Line])

    def apply_meta(self, meta: Meta) -> None:
        """Copy parsed metadata into a project's ``meta`` (only keys present in the file)."""
        for key, value in self.meta.items():
            setattr(meta, key, value)


def tokens_from_text(text: str) -> list[Token]:
    """Tokenise a lyric line into untimed project tokens."""
    return [
        Token(
            text=item.text,
            ruby=item.ruby,
            ruby_source="manual" if item.ruby else None,
        )
        for item in tokenize(text)
    ]


def _singer_id(tag: str, singers: list[Singer]) -> str:
    """Resolve a ``[tag]`` to a singer id, registering custom singers on first use."""
    alias = _SINGER_ALIASES.get(tag.strip().lower())
    if alias is not None:
        return alias
    label = tag.strip()
    for singer in singers:
        if singer.label == label or singer.id == label:
            return singer.id
    used_slots = {singer.theme_slot for singer in singers[3:]}
    slot = next((s for s in _FALLBACK_SLOTS if s not in used_slots), "duet")
    base = re.sub(r"[^\w]+", "-", label.lower()).strip("-") or "singer"
    candidate, counter = base, 2
    existing = {singer.id for singer in singers}
    while candidate in existing:
        candidate = f"{base}-{counter}"
        counter += 1
    singers.append(Singer(id=candidate, label=label, theme_slot=slot))
    return candidate


def parse_lyrics_text(text: str) -> ParsedLyrics:
    """Parse the content of a lyrics ``.txt`` file.

    Raises:
        LyricsFormatError: If the file contains no lyric lines.
    """
    result = ParsedLyrics()
    current_singer = "m"
    paragraph = 0
    pending_break = False

    for raw in text.lstrip("﻿").splitlines():
        stripped = raw.strip()
        if not stripped:
            pending_break = bool(result.lines)
            continue
        if stripped.startswith("#"):
            match = _META_LINE.match(stripped)
            if match:
                key = _META_KEYS.get(match.group(1).strip().lower())
                if key:
                    result.meta[key] = match.group(2).strip()
            continue
        id_tag = _LRC_ID_TAG.match(stripped)
        if id_tag:
            key = _LRC_ID_KEYS.get(id_tag.group(1).lower())
            if key and id_tag.group(2).strip():
                result.meta.setdefault(key, id_tag.group(2).strip())
            continue
        stripped = _INLINE_TIME_TAGS.sub("", _LEADING_TIME_TAGS.sub("", stripped)).strip()
        if not stripped:
            continue

        match = _TAG.match(stripped)
        if match:
            current_singer = _singer_id(match.group(1), result.singers)
            stripped = stripped[match.end() :]
            if not stripped:
                continue  # a tag on its own line switches the singer for the lines below

        tokens = tokens_from_text(stripped)
        if not tokens:
            continue
        if pending_break:
            paragraph += 1
            pending_break = False
        result.lines.append(
            Line(
                id=f"L{len(result.lines) + 1:03d}",
                singer=current_singer,
                paragraph=paragraph,
                tokens=tokens,
            )
        )

    if not result.lines:
        raise LyricsFormatError(
            "歌詞檔裡沒有任何歌詞。",
            "The lyrics file contains no lyric lines.",
            hint_zh="每一行一句歌詞；以 # 開頭的行是歌曲資訊，空行代表段落分隔。",
            hint_en="Write one lyric line per row; rows starting with # are metadata and "
            "blank rows separate paragraphs.",
        )
    return result


def decode_text(data: bytes) -> str | None:
    """Decode text in UTF-8, UTF-16 (with BOM), Big5 or GB18030; ``None`` if nothing fits.

    UTF-16 is only tried when a byte-order mark is present, because almost any even-length
    byte string "decodes" as UTF-16.  Between the two legacy Chinese encodings the one whose
    result contains more everyday characters is chosen.
    """
    if data.startswith(codecs.BOM_UTF8):
        unicode_encoding = "utf-8-sig"
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        unicode_encoding = "utf-16"
    else:
        unicode_encoding = "utf-8"
    try:
        return data.decode(unicode_encoding)
    except UnicodeError:
        pass
    candidates: list[tuple[int, str]] = []
    for encoding in ("big5hkscs", "gb18030"):
        try:
            text = data.decode(encoding)
        except UnicodeError:
            continue
        candidates.append((sum(1 for char in text if char in _COMMON_HANZI), text))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def read_text_file(path: Path) -> str:
    """Read a text file, trying the encodings commonly used for Chinese lyrics.

    Raises:
        LyricsFormatError: If the file cannot be read or decoded.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LyricsFormatError(
            f"無法讀取歌詞檔：{path}",
            f"Cannot read the lyrics file: {path}",
            detail=str(exc),
        ) from exc
    decoded = decode_text(data)
    if decoded is not None:
        return decoded
    raise LyricsFormatError(
        f"無法辨識歌詞檔的文字編碼：{path.name}",
        f"Cannot detect the text encoding of {path.name}.",
        hint_zh="請把檔案另存為 UTF-8 編碼。",
        hint_en="Please save the file as UTF-8.",
    )


def parse_lyrics_file(path: Path) -> ParsedLyrics:
    """Parse a lyrics ``.txt`` file."""
    return parse_lyrics_text(read_text_file(path))
