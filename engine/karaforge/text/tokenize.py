r"""Script-aware tokenisation of lyric text.

A *token* is the unit that gets its own start/end time and is filled as one piece:

* one CJK ideograph, one Hangul syllable block, or one kana (with a following small kana or
  prolonged-sound mark);
* one "word" of letters and digits for alphabetic scripts (``don't`` and ``3.14`` stay whole).

Punctuation and whitespace never form tokens of their own: closing punctuation and the
whitespace after a unit attach to it, opening punctuation attaches to the unit that follows.
Joining the ``text`` of every token therefore reproduces the (whitespace-normalised) line.

A reading can be forced with ``字{reading}``; it is attached to the token that contains the
character right before the brace.  Use ``\{`` and ``\}`` for literal braces.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class TokenKind(StrEnum):
    """What kind of unit a token's core is."""

    HAN = "han"
    KANA = "kana"
    HANGUL = "hangul"
    WORD = "word"
    NONE = "none"
    """Punctuation only: nothing to time (e.g. a line that is just ``……``)."""


@dataclass(frozen=True)
class TextToken:
    """One token produced by :func:`tokenize`."""

    text: str
    """Full text, including attached punctuation and whitespace."""
    core: str
    """The timed unit itself, without punctuation or whitespace."""
    kind: TokenKind
    ruby: str | None = None
    """Reading given by the user with ``字{reading}``."""


_SMALL_KANA = frozenset("ぁぃぅぇぉゃゅょゎゕゖァィゥェォャュョヮヵヶーｧｨｩｪｫｬｭｮｰ")
_APOSTROPHES = frozenset("'’＇ʼ")
_NUMBER_JOINERS = frozenset(".,")


def is_han(char: str) -> bool:
    """Whether ``char`` is a CJK ideograph (including 々 and 〇)."""
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x323AF
        or code in (0x3005, 0x3007)
    )


def is_kana(char: str) -> bool:
    """Whether ``char`` is hiragana or katakana (full or half width)."""
    code = ord(char)
    return (
        0x3041 <= code <= 0x3096
        or 0x30A1 <= code <= 0x30FA
        or code == 0x30FC
        or 0x31F0 <= code <= 0x31FF
        or 0xFF66 <= code <= 0xFF9D
    )


def is_hangul(char: str) -> bool:
    """Whether ``char`` is a precomposed Hangul syllable."""
    return 0xAC00 <= ord(char) <= 0xD7A3


def _classify(char: str) -> str:
    """Return one of: han, kana, hangul, word, mark, space, open, close."""
    if char.isspace():
        return "space"
    if is_han(char):
        return "han"
    if is_kana(char):
        return "kana"
    if is_hangul(char):
        return "hangul"
    category = unicodedata.category(char)
    if category[0] in "LN":
        return "word"
    if category[0] == "M":
        return "mark"
    if category in ("Ps", "Pi"):
        return "open"
    return "close"


def _extract_readings(text: str) -> tuple[str, dict[int, str]]:
    """Strip ``{reading}`` annotations.

    Returns the cleaned text and a map from the index (in the cleaned text) of the annotated
    character to its reading.
    """
    cleaned: list[str] = []
    readings: dict[int, str] = {}
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\" and index + 1 < length and text[index + 1] in "{}":
            cleaned.append(text[index + 1])
            index += 2
            continue
        if char == "{" and cleaned and not cleaned[-1].isspace():
            close = text.find("}", index + 1)
            if close != -1:
                reading = text[index + 1 : close].strip()
                if reading:
                    readings[len(cleaned) - 1] = reading
                index = close + 1
                continue
        cleaned.append(char)
        index += 1
    return "".join(cleaned), readings


class _Builder:
    """Accumulates the prefix / core / suffix of the token being built."""

    def __init__(self) -> None:
        self.tokens: list[TextToken] = []
        self.prefix = ""
        self.core = ""
        self.suffix = ""
        self.kind = TokenKind.NONE
        self.ruby: str | None = None

    def flush(self) -> None:
        if not self.core:
            return
        self.tokens.append(
            TextToken(
                text=self.prefix + self.core + self.suffix,
                core=self.core,
                kind=self.kind,
                ruby=self.ruby,
            )
        )
        self.prefix = self.core = self.suffix = ""
        self.kind = TokenKind.NONE
        self.ruby = None

    def finish(self) -> list[TextToken]:
        dangling = self.prefix if not self.core else ""
        self.flush()
        if dangling:
            if self.tokens:
                last = self.tokens[-1]
                self.tokens[-1] = TextToken(last.text + dangling, last.core, last.kind, last.ruby)
            else:
                self.tokens.append(TextToken(dangling, "", TokenKind.NONE))
        return self.tokens


def tokenize(text: str) -> list[TextToken]:
    """Split one lyric line into tokens.

    Args:
        text: A single line of lyrics (no line breaks).  Leading and trailing whitespace is
            ignored and runs of whitespace collapse to their first character.

    Returns:
        The tokens in order.  An empty or whitespace-only line gives an empty list.
    """
    cleaned, readings = _extract_readings(unicodedata.normalize("NFC", text).strip())
    builder = _Builder()
    length = len(cleaned)

    for index, char in enumerate(cleaned):
        kind = _classify(char)

        # Apostrophes inside a word and separators inside a number belong to the word.
        if kind == "close" and builder.core and not builder.suffix and index + 1 < length:
            following = cleaned[index + 1]
            if builder.kind is TokenKind.WORD and (
                (char in _APOSTROPHES and _classify(following) == "word")
                or (char in _NUMBER_JOINERS and builder.core[-1].isdigit() and following.isdigit())
            ):
                kind = "word"

        if kind == "space":
            if builder.core and (not builder.suffix or not builder.suffix[-1].isspace()):
                builder.suffix += " " if char in "\t\r\n\v\f" else char
            continue
        if kind == "mark":
            if builder.suffix:
                builder.suffix += char
            elif builder.core:
                builder.core += char
            else:
                builder.prefix += char
        elif kind == "open":
            builder.flush()
            builder.prefix += char
        elif kind == "close":
            if builder.core:
                builder.suffix += char
            else:
                builder.prefix += char
        else:
            token_kind = TokenKind(kind)
            continues_word = (
                token_kind is TokenKind.WORD
                and builder.kind is TokenKind.WORD
                and not builder.suffix
            )
            continues_kana = (
                token_kind is TokenKind.KANA
                and builder.kind is TokenKind.KANA
                and not builder.suffix
                and char in _SMALL_KANA
            )
            if builder.core and not (continues_word or continues_kana):
                builder.flush()
            builder.core += char
            builder.kind = token_kind

        if index in readings and builder.core:
            builder.ruby = readings[index]

    return builder.finish()


def core_of(text: str) -> str:
    """Return the timed unit inside a token's text (strip attached punctuation and spaces)."""
    tokens = tokenize(text)
    return "".join(token.core for token in tokens)


def kind_of(text: str) -> TokenKind:
    """Classify a token's text by the kind of its first unit."""
    tokens = tokenize(text)
    return tokens[0].kind if tokens else TokenKind.NONE


def normalize_core(core: str) -> str:
    """Normalise a unit for comparison: NFKC (full-width → ASCII) and case-folded."""
    return unicodedata.normalize("NFKC", core).casefold()
