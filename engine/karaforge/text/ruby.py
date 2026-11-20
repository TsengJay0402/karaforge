"""Readings (注音 / 拼音) for Chinese lyrics, shown as small ruby text above the characters.

How a reading is chosen, in this order:

1. **Words** — the line is converted to Simplified with OpenCC's Taiwan table (which also
   tells the particle 著 from 著名) and cut into words by pypinyin's phrase dictionary; a
   character inside a known word takes the word's reading (銀行 → háng, 音樂 → yuè).
2. **Function words** — the handful of very frequent characters whose reading depends on
   grammar rather than on a word (得, 地, 了, 著, 還) follow small context rules when no word
   covered them, and 一 / 不 get their tone sandhi.
3. **The character itself** — otherwise the most common reading, with the Traditional form
   deciding between characters that Simplified merges (乾 / 幹, 髮 / 發, 隻 / 只 …).
4. **Taiwan readings** — for ``zh-TW`` a table replaces the readings that differ from the
   Mainland standard pypinyin follows (垃圾 ㄌㄜˋ ㄙㄜˋ, 寂寞 ㄐㄧˊ ㄇㄛˋ, 擁抱 ㄩㄥˇ ㄅㄠˋ …).

This is a dictionary method, not a language model: it cannot know that 還 in 「怎麼還」 is a
verb unless a rule says so.  ``docs/ruby.md`` reports how often it is right on a test set of
polyphonic characters; a reading given by hand (``行{ㄏㄤˊ}`` in the lyrics, or in the
editor) always wins and is never touched.

Internally a reading is Hanyu Pinyin with a tone digit (``lv4``, neutral tone ``5``).
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Literal

from opencc import OpenCC
from pypinyin import Style, pinyin
from pypinyin.constants import PHRASES_DICT
from pypinyin.contrib.tone_convert import tone3_to_tone
from pypinyin.seg import simpleseg
from pypinyin.style import convert as convert_style

from karaforge.project.schema import Line, Project, Token
from karaforge.text.script import script_config
from karaforge.text.tokenize import core_of, is_han

RubyKind = Literal["zhuyin", "pinyin"]
KINDS: tuple[RubyKind, ...] = ("zhuyin", "pinyin")

_BOPOMOFO_START, _BOPOMOFO_END = 0x3105, 0x312F
_NEUTRAL_MARK = "˙"

# --- characters that Simplified merges but Traditional tells apart ----------------------------
_BY_TRADITIONAL: dict[str, str] = {
    "乾": "gan1",
    "幹": "gan4",
    "髮": "fa4",
    "發": "fa1",
    "隻": "zhi1",
    "鬥": "dou4",
    "彆": "bie4",
    "劃": "hua4",
    "僕": "pu2",
    "儘": "jin3",
    "捲": "juan3",
    "麼": "me5",
}
"""Reading of a Traditional character when no word decided it."""

# --- Taiwan (MOE) readings that differ from the Mainland standard ------------------------------
_TAIWAN_WORDS: dict[str, tuple[str, ...]] = {
    "垃圾": ("le4", "se4"),
    "法國": ("fa4", "guo2"),
    "法蘭西": ("fa4", "lan2", "xi1"),
    "暴露": ("pu4", "lu4"),
    "說服": ("shui4", "fu2"),
    "悄悄": ("qiao3", "qiao3"),
    "蝸牛": ("gua1", "niu2"),
    "人質": ("ren2", "zhi4"),
}
_TAIWAN_CHARS: dict[str, str] = {
    "期": "qi2",
    "企": "qi4",
    "微": "wei2",
    "危": "wei2",
    "薇": "wei2",
    "液": "yi4",
    "擁": "yong3",
    "惜": "xi2",
    "夕": "xi4",
    "昔": "xi2",
    "息": "xi2",
    "寂": "ji2",
    "跡": "ji1",
    "蹟": "ji1",
    "績": "ji1",
    "究": "jiu4",
    "突": "tu2",
    "俄": "e4",
    "髮": "fa3",
    "帆": "fan2",
    "崖": "yai2",
    "攜": "xi1",
    "堤": "ti2",
    "誼": "yi2",
    "亞": "ya3",
    "質": "zhi2",
    "血": "xie3",
    "熟": "shou2",
    "跌": "die2",
    "擊": "ji2",
    "綜": "zong4",
    "識": "shi4",
    "偽": "wei4",
    "顫": "zhan4",
}

# --- context of the function-word rules --------------------------------------------------------
_PRONOUNS = frozenset("我你妳您他她它牠祂")
_BEFORE_MUST = _PRONOUNS | frozenset("們就都也還才總非可便又更必只誰")
"""得 after one of these is the modal "must" (我得走了)."""
_AFTER_GET = frozenset("到了以意失罪救出知獎勝益逞手體分過起來去")
"""得 before one of these is the verb or part of a complement (得到, 得了)."""
_RETURN_OBJECTS = frozenset("給清債錢手擊原鄉願俗款")
"""還 before one of these is the verb "to return" (還給, 還清, 還手)."""
_PREDICATE_STARTS = frozenset(
    "在是有要會能想記愛不沒好很真太說笑哭來去等懂怕敢該可願需覺以跟和對把被給為像都也還就才嗎呢吧啊"
)
"""After 「還 + pronoun」 one of these shows that 還 is the adverb (還你在 …)."""
_ADVERB_STEMS = frozenset(
    {
        "不停",
        "不斷",
        "拼命",
        "努力",
        "用力",
        "盡情",
        "任性",
        "溫柔",
        "安靜",
        "勇敢",
        "瘋狂",
        "自由",
        "快樂",
        "幸福",
        "開心",
        "輕聲",
        "大聲",
        "小心",
        "用心",
        "認真",
        "真心",
        "狠心",
        "默默",
        "忍不住",
    }
)
"""Words that 地 turns into adverbs (不停地, 溫柔地); reduplications need no list."""
_CATCHES = frozenset("火迷涼魔慌道")
"""著了 + one of these: 著 is zháo (著了火, 著了迷)."""
_NUMERALS = frozenset("零一二三四五六七八九十百千萬億兩")
_SANDHI = frozenset("一不")
_ONE_STAYS_AFTER = frozenset("第十初期週周拜唯統萬同之專合單逐劃")
"""一 keeps its first tone after these: ordinals, weekdays, and words that end in 一 (唯一)."""
_DATE_AFTER = frozenset("月號日")


def default_kind(language: str) -> RubyKind | None:
    """The kind of reading a language is annotated with by default.

    Zhuyin for Traditional Chinese (``zh-TW``, plain ``zh``), Pinyin for ``zh-CN`` and
    ``zh-HK``; ``None`` for every other language — Han characters in Japanese lyrics are not
    read in Mandarin.
    """
    config = script_config(language)
    if config is None:
        return None
    return "zhuyin" if config == "s2tw" else "pinyin"


def uses_taiwan_readings(language: str) -> bool:
    """Whether readings follow the Taiwan standard (true for ``zh-TW`` and plain ``zh``)."""
    return script_config(language) == "s2tw"


@lru_cache(maxsize=2)
def _simplifier(config: str) -> OpenCC:
    return OpenCC(config)


def _simplify(text: str) -> str:
    """Simplified form with exactly one character per input character."""
    for config in ("tw2s", "t2s"):
        simplified = _simplifier(config).convert(text)
        if len(simplified) == len(text):
            return simplified
    return text


def _tone3(marked: str) -> str:
    """Pinyin with tone marks → tone digit at the end (``5`` for the neutral tone)."""
    plain = convert_style(marked, Style.TONE3, strict=False)
    return plain if plain[-1:].isdigit() else plain + "5"


def _default(char: str) -> str | None:
    """Most common reading of a single (Simplified) character."""
    found = pinyin(char, style=Style.TONE3, neutral_tone_with_five=True, heteronym=False)
    reading = found[0][0] if found and found[0] else ""
    return reading if reading and reading[-1].isdigit() else None


def _tone(reading: str | None) -> int:
    return int(reading[-1]) if reading and reading[-1].isdigit() else 0


def _function_word(text: str, index: int, readings: Sequence[str | None]) -> str | None:
    """Reading of a function word at ``index`` from its neighbours, or ``None`` for no opinion."""
    char = text[index]
    before = text[index - 1] if index > 0 and is_han(text[index - 1]) else ""
    after = text[index + 1] if index + 1 < len(text) and is_han(text[index + 1]) else ""
    second = text[index + 2] if index + 2 < len(text) and is_han(text[index + 2]) else ""
    if char == "得":
        if before == "不" or not before:
            return "de2"
        if before in _BEFORE_MUST:
            # 我得走了 (must) — but 我得到了, 我得了獎 (got).
            return "dei3" if after and after not in _AFTER_GET else "de2"
        # After a verb or an adjective it introduces the complement: 跑得快, 受得了, 做得到.
        return "de5"
    if char == "地":
        reduplicated = index >= 2 and text[index - 1] == text[index - 2] and bool(before)
        stem = any(text[max(0, index - len(word)) : index] == word for word in _ADVERB_STEMS)
        return "de5" if reduplicated or stem else None
    if char == "了":
        # 忘不了, 受得了: "cannot / can …" — but 我得了獎 and a plain 不了 keep the particle.
        verb = text[index - 2] if index >= 2 and is_han(text[index - 2]) else ""
        if before == "不" and verb:
            return "liao3"
        if before == "得" and verb and verb not in _BEFORE_MUST:
            return "liao3"
        return "le5"
    if char == "著":
        if before in ("不", "得"):
            return "zhao2"
        if after == "了" and second in _CATCHES:
            return "zhao2"
        return None
    if char == "還":
        if not after:
            return "huan2" if before else None
        if after in _RETURN_OBJECTS:
            return "huan2"
        if after in _PRONOUNS and second not in _PREDICATE_STARTS:
            return "huan2"
        return "hai2"
    if char == "一":
        ordinal = before in _ONE_STAYS_AFTER or before in _NUMERALS
        if not after or ordinal or after in _NUMERALS or after in _DATE_AFTER:
            return "yi1"
        return "yi2" if _tone(readings[index + 1]) == 4 else "yi4"
    if char == "不":
        return "bu2" if after and _tone(readings[index + 1]) == 4 else "bu4"
    return None


def han_readings(text: str, *, taiwan: bool = True) -> list[str | None]:
    """Reading of every character of ``text`` (``None`` where there is nothing to read).

    Args:
        text: A lyric line in Traditional or Simplified Chinese; other text may be mixed in.
        taiwan: Use the Taiwan readings where they differ from the Mainland standard.

    Returns:
        One entry per character of ``text``: Pinyin with a tone digit, or ``None``.
    """
    simplified = _simplify(text)
    readings: list[str | None] = [None] * len(text)
    in_word = [False] * len(text)
    start = 0
    while start < len(text):
        if not is_han(text[start]):
            start += 1
            continue
        stop = start
        while stop < len(text) and is_han(text[stop]):
            stop += 1
        run = simplified[start:stop]
        segments = [str(segment) for segment in simpleseg.seg(run)]
        offset = start
        for segment in segments if "".join(segments) == run else []:
            words = PHRASES_DICT.get(segment) if len(segment) > 1 else None
            for position, item in enumerate(words or []):
                if position < len(segment) and item:
                    readings[offset + position] = _tone3(item[0])
                    in_word[offset + position] = True
            offset += len(segment)
        start = stop
    for index, char in enumerate(text):
        if readings[index] is None and is_han(char):
            readings[index] = _BY_TRADITIONAL.get(char) or _default(simplified[index])
    # Right to left, so that 一 and 不 see the final tone of what follows them.
    for index in range(len(text) - 1, -1, -1):
        # 一 and 不 change their tone by rule everywhere, also inside dictionary words, whose
        # entries are not consistent about it.
        if readings[index] is None or (in_word[index] and text[index] not in _SANDHI):
            continue
        decided = _function_word(text, index, readings)
        if decided is not None:
            readings[index] = decided
    if taiwan:
        for index, char in enumerate(text):
            if readings[index] is not None and char in _TAIWAN_CHARS:
                readings[index] = _TAIWAN_CHARS[char]
        for word, word_readings in _TAIWAN_WORDS.items():
            start = text.find(word)
            while start >= 0:
                readings[start : start + len(word)] = list(word_readings)
                start = text.find(word, start + len(word))
    return readings


def format_reading(reading: str, kind: RubyKind) -> str:
    """Write an internal reading (``lv4``) as Zhuyin (``ㄌㄩˋ``) or Pinyin (``lǜ``).

    The neutral-tone dot of Zhuyin goes in front of the syllable (``˙ㄇㄚ``), as it is written
    in Taiwan.
    """
    marked = tone3_to_tone(reading)
    if kind == "pinyin":
        return marked
    zhuyin = convert_style(marked, Style.BOPOMOFO, strict=False)
    if reading.endswith("5") or _NEUTRAL_MARK in zhuyin:
        return _NEUTRAL_MARK + zhuyin.replace(_NEUTRAL_MARK, "")
    return zhuyin


def line_readings(texts: Sequence[str], kind: RubyKind, *, taiwan: bool = True) -> list[str | None]:
    """Ruby text for the tokens of one line.

    Args:
        texts: The ``text`` of each token, in order (their concatenation is the line).
        kind: Zhuyin or Pinyin.
        taiwan: Use the Taiwan readings.

    Returns:
        One entry per token: the formatted reading of a Han character, ``None`` otherwise.
    """
    line = "".join(texts)
    readings = han_readings(line, taiwan=taiwan)
    result: list[str | None] = []
    offset = 0
    for text in texts:
        core = core_of(text)
        reading: str | None = None
        if len(core) == 1 and is_han(core):
            position = offset + max(text.find(core), 0)
            raw = readings[position] if position < len(readings) else None
            reading = format_reading(raw, kind) if raw else None
        result.append(reading)
        offset += len(text)
    return result


def kind_of(lines: Sequence[Line]) -> RubyKind | None:
    """Which kind the automatic readings of a project are in (``None`` when it has none)."""
    found: RubyKind | None = None
    for line in lines:
        for token in line.tokens:
            if token.ruby and token.ruby_source == "auto":
                if any(_BOPOMOFO_START <= ord(char) <= _BOPOMOFO_END for char in token.ruby):
                    return "zhuyin"
                found = "pinyin"
    return found


def annotate_line(line: Line, kind: RubyKind, *, taiwan: bool = True) -> Line:
    """A copy of ``line`` with automatic readings on its Han tokens.

    Readings given by hand stay exactly as they are; automatic readings are replaced, and
    removed from tokens that are not Han characters (any more).
    """
    readings = line_readings([token.text for token in line.tokens], kind, taiwan=taiwan)
    tokens: list[Token] = []
    for token, reading in zip(line.tokens, readings, strict=True):
        if token.ruby_source == "manual" and token.ruby:
            tokens.append(token)
        elif reading is not None:
            tokens.append(token.model_copy(update={"ruby": reading, "ruby_source": "auto"}))
        elif token.ruby is not None or token.ruby_source is not None:
            tokens.append(token.model_copy(update={"ruby": None, "ruby_source": None}))
        else:
            tokens.append(token)
    return line.model_copy(update={"tokens": tokens})


def clear_line(line: Line) -> Line:
    """A copy of ``line`` without automatic readings (manual ones stay)."""
    tokens = [
        token.model_copy(update={"ruby": None, "ruby_source": None})
        if token.ruby_source == "auto"
        else token
        for token in line.tokens
    ]
    return line.model_copy(update={"tokens": tokens})


def annotate_project(project: Project, kind: RubyKind | None = None) -> int:
    """Give every Han token of a Chinese project an automatic reading.

    Args:
        project: Modified in place.
        kind: Zhuyin or Pinyin; by default the kind the project already uses, else the
            default of its language.  Nothing happens for a language that is not Chinese
            unless a kind is given.

    Returns:
        The number of tokens that now carry an automatic reading.
    """
    chosen = kind or kind_of(project.lines) or default_kind(project.meta.language)
    if chosen is None:
        return 0
    taiwan = script_config(project.meta.language) in (None, "s2tw")
    project.lines = [annotate_line(line, chosen, taiwan=taiwan) for line in project.lines]
    return sum(token.ruby_source == "auto" for line in project.lines for token in line.tokens)


def clear_project(project: Project) -> int:
    """Remove every automatic reading (manual ones stay); returns how many were removed."""
    before = sum(token.ruby_source == "auto" for line in project.lines for token in line.tokens)
    project.lines = [clear_line(line) for line in project.lines]
    return before
