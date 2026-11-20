"""Romanisation of lyric tokens for fuzzy matching and CTC alignment.

Every token is reduced to a short string of lower-case Latin letters that approximates how
it sounds: toneless Hanyu Pinyin for Chinese characters, the word itself for alphabetic
scripts, Hepburn rōmaji for kana and Revised Romanization for Hangul.  Comparing these
strings instead of the original characters makes the lyric/ASR matching tolerant of
homophones, of Traditional/Simplified differences and of near-miss recognitions.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from functools import lru_cache

from opencc import OpenCC
from pypinyin import Style, lazy_pinyin
from pypinyin.pinyin_dict import pinyin_dict as PINYIN_DICT  # noqa: N812
from pypinyin.style import convert as convert_pinyin_style

from karaforge.text.tokenize import TokenKind, is_han

_TONE_MARKS = "ˊˇˋ˙ˉ"
_ZHUYIN_CHARS = re.compile(r"^[ㄅ-ㄯㆠ-ㆿ" + _TONE_MARKS + r"\s]+$")


@lru_cache(maxsize=1)
def _t2s() -> OpenCC:
    return OpenCC("t2s")


def to_simplified(text: str) -> str:
    """Convert Traditional Chinese to Simplified (character by character, same length)."""
    return _t2s().convert(text)


def _toneless(pinyin: str) -> str:
    """Strip tone marks from a pinyin syllable and write ``ü`` as ``v``."""
    decomposed = unicodedata.normalize("NFKD", pinyin).replace("u\u0308", "v")
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z]", "", plain)


@lru_cache(maxsize=1)
def _zhuyin_table() -> dict[str, str]:
    """Map toneless zhuyin strings to toneless pinyin.

    The syllable inventory comes from pypinyin's own character dictionary, so only real,
    correctly spelled syllables (``wo``, ``yue``, ``xiong`` …) are produced.
    """
    syllables: set[str] = set()
    for readings in PINYIN_DICT.values():
        for reading in readings.split(","):
            syllable = _toneless(reading)
            if syllable:
                syllables.add(syllable)
    table: dict[str, str] = {}
    for syllable in sorted(syllables):
        try:
            zhuyin = convert_pinyin_style(syllable, Style.BOPOMOFO, strict=False)
        except (KeyError, ValueError, IndexError):
            continue
        zhuyin = "".join(ch for ch in zhuyin if ch not in _TONE_MARKS)
        if zhuyin and _ZHUYIN_CHARS.match(zhuyin):
            table.setdefault(zhuyin, syllable)
    return table


def zhuyin_to_pinyin(zhuyin: str) -> str | None:
    """Convert one zhuyin (bopomofo) syllable to toneless pinyin, or ``None`` if unknown."""
    bare = "".join(ch for ch in zhuyin if ch not in _TONE_MARKS and not ch.isspace())
    return _zhuyin_table().get(bare)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_reading(reading: str) -> str | None:
    """Reduce a user-supplied reading (zhuyin or pinyin, any tone notation) to letters.

    Returns:
        Lower-case ASCII letters (``ü`` is written ``v``), or ``None`` when the reading is
        in neither notation.
    """
    text = reading.strip()
    if not text:
        return None
    if _ZHUYIN_CHARS.match(text):
        syllables = [zhuyin_to_pinyin(part) for part in text.split()]
        if all(syllables):
            return "".join(s for s in syllables if s)
        return None
    return _toneless(text) or None


def han_readings(run: str) -> list[str]:
    """Toneless pinyin for each character of a run of Chinese characters.

    The run is converted to Simplified first because pypinyin's phrase dictionary — which
    is what resolves polyphonic characters such as 重 in 重複 — is keyed by Simplified text.
    """
    if not run:
        return []
    readings = lazy_pinyin(to_simplified(run), style=Style.NORMAL, v_to_u=False)
    if len(readings) != len(run):
        # pypinyin groups characters it does not know; fall back to one call per character.
        readings = [
            (lazy_pinyin(to_simplified(ch), style=Style.NORMAL, v_to_u=False) or [""])[0]
            for ch in run
        ]
    return [reading if reading.isascii() and reading.isalpha() else "" for reading in readings]


_KANA_ROMAJI = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ゔ": "vu", "っ": "", "ー": "",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa",
}  # fmt: skip


def kana_reading(kana: str) -> str:
    """Hepburn-style rōmaji for a kana token (one kana plus optional small kana)."""
    text = unicodedata.normalize("NFKC", kana)
    hiragana = "".join(chr(ord(ch) - 0x60) if 0x30A1 <= ord(ch) <= 0x30F6 else ch for ch in text)
    result = ""
    for ch in hiragana:
        piece = _KANA_ROMAJI.get(ch, "")
        if ch in "ゃゅょ" and result.endswith("i") and len(result) >= 2:
            # きゃ → kya, しゃ → sha, ちゃ → cha, じゃ → ja
            stem = result[:-1]
            piece = piece[1:] if stem.endswith(("sh", "ch", "j")) else piece
            result = stem + piece
        else:
            result += piece
    return result


_HANGUL_INITIALS = (
    "g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch",
    "k", "t", "p", "h",
)  # fmt: skip
_HANGUL_MEDIALS = (
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u",
    "wo", "we", "wi", "yu", "eu", "ui", "i",
)  # fmt: skip
_HANGUL_FINALS = (
    "", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m",
    "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t",
)  # fmt: skip


def hangul_reading(syllable: str) -> str:
    """Revised Romanization of one precomposed Hangul syllable (no assimilation rules)."""
    result = ""
    for ch in syllable:
        code = ord(ch) - 0xAC00
        if not 0 <= code <= 11171:
            continue
        initial, rest = divmod(code, 588)
        medial, final = divmod(rest, 28)
        result += _HANGUL_INITIALS[initial] + _HANGUL_MEDIALS[medial] + _HANGUL_FINALS[final]
    return result


def word_reading(word: str) -> str:
    """Letters and digits of an alphabetic word, accents removed, lower-cased."""
    plain = _strip_accents(unicodedata.normalize("NFKC", word)).lower()
    return re.sub(r"[^a-z0-9]", "", plain)


def romanize_tokens(
    cores: Sequence[str],
    kinds: Sequence[TokenKind],
    manual: Sequence[str | None] | None = None,
) -> list[str]:
    """Romanise the tokens of one line.

    Consecutive Chinese characters are converted together so that phrase context can
    resolve polyphonic characters.  A reading supplied by the user (``字{讀音}``) always wins.

    Args:
        cores: Core text of every token of the line.
        kinds: Kind of every token.
        manual: Optional user-supplied reading per token.

    Returns:
        One lower-case ASCII string per token; empty when nothing pronounceable is known.
    """
    count = len(cores)
    result = [""] * count
    index = 0
    while index < count:
        kind = kinds[index]
        if kind is TokenKind.HAN:
            end = index
            while end < count and kinds[end] is TokenKind.HAN:
                end += 1
            run = "".join(cores[index:end])
            if len(run) == end - index and all(is_han(ch) for ch in run):
                result[index:end] = han_readings(run)
            else:
                for position in range(index, end):
                    result[position] = "".join(han_readings(cores[position]))
            index = end
            continue
        if kind is TokenKind.WORD:
            result[index] = word_reading(cores[index])
        elif kind is TokenKind.KANA:
            result[index] = kana_reading(cores[index])
        elif kind is TokenKind.HANGUL:
            result[index] = hangul_reading(cores[index])
        index += 1

    if manual is not None:
        for position, reading in enumerate(manual):
            if reading:
                normalized = normalize_reading(reading)
                if normalized:
                    result[position] = normalized
    return result
