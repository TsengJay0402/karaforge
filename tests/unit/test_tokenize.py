from __future__ import annotations

import pytest

from karaforge.text.tokenize import (
    TokenKind,
    core_of,
    is_han,
    is_hangul,
    is_kana,
    kind_of,
    normalize_core,
    tokenize,
)


def test_han_per_character() -> None:
    tokens = tokenize("我是誰")
    assert [(token.core, token.kind) for token in tokens] == [
        ("我", TokenKind.HAN),
        ("是", TokenKind.HAN),
        ("誰", TokenKind.HAN),
    ]
    assert [token.text for token in tokens] == ["我", "是", "誰"]


def test_english_words() -> None:
    tokens = tokenize("hello world")
    assert [(token.core, token.kind) for token in tokens] == [
        ("hello", TokenKind.WORD),
        ("world", TokenKind.WORD),
    ]
    assert [token.text for token in tokens] == ["hello ", "world"]


def test_mixed_chinese_english() -> None:
    tokens = tokenize("我 love 你")
    assert [(token.core, token.kind) for token in tokens] == [
        ("我", TokenKind.HAN),
        ("love", TokenKind.WORD),
        ("你", TokenKind.HAN),
    ]
    assert [token.text for token in tokens] == ["我 ", "love ", "你"]


def test_trailing_punctuation_attaches_to_previous_token() -> None:
    tokens = tokenize("你好,世界!")
    assert [token.text for token in tokens] == ["你", "好,", "世", "界!"]
    assert [token.core for token in tokens] == ["你", "好", "世", "界"]


def test_leading_punctuation_attaches_to_following_token() -> None:
    tokens = tokenize("(附)註")
    assert [token.text for token in tokens] == ["(附)", "註"]
    assert [token.core for token in tokens] == ["附", "註"]


def test_whitespace_is_normalized() -> None:
    tokens = tokenize("  a \t b  ")
    assert [token.text for token in tokens] == ["a ", "b"]
    assert core_of("  a \t b  ") == "ab"


def test_apostrophe_stays_inside_word() -> None:
    tokens = tokenize("don't stop")
    assert [token.core for token in tokens] == ["don't", "stop"]
    assert [token.kind for token in tokens] == [TokenKind.WORD, TokenKind.WORD]


def test_number_with_decimal_point_stays_whole() -> None:
    tokens = tokenize("3.14 秒")
    assert [token.core for token in tokens] == ["3.14", "秒"]
    assert [token.kind for token in tokens] == [TokenKind.WORD, TokenKind.HAN]


def test_hyphen_splits_words() -> None:
    tokens = tokenize("rock-n-roll")
    assert [token.core for token in tokens] == ["rock", "n", "roll"]
    assert [token.text for token in tokens] == ["rock-", "n-", "roll"]


def test_ruby_attaches_to_token_before_brace() -> None:
    tokens = tokenize("重{ㄔㄨㄥˊ}複")
    assert len(tokens) == 2
    assert tokens[0].core == "重"
    assert tokens[0].ruby == "ㄔㄨㄥˊ"
    assert tokens[1].core == "複"
    assert tokens[1].ruby is None


def test_ruby_with_english_word() -> None:
    tokens = tokenize("love{拉夫}你")
    assert tokens[0].core == "love"
    assert tokens[0].ruby == "拉夫"


def test_escaped_braces_are_literal() -> None:
    tokens = tokenize(r"\{abc\}")
    assert len(tokens) == 1
    assert tokens[0].core == "abc"
    assert tokens[0].text == "{abc}"
    assert tokens[0].ruby is None


def test_punctuation_only_line_gives_single_none_token() -> None:
    tokens = tokenize("……")
    assert len(tokens) == 1
    assert tokens[0].kind is TokenKind.NONE
    assert tokens[0].core == ""
    assert tokens[0].text == "……"


def test_empty_string_gives_empty_list() -> None:
    assert tokenize("") == []


def test_whitespace_only_gives_empty_list() -> None:
    assert tokenize("   \t ") == []


def test_small_kana_joins_previous_kana() -> None:
    tokens = tokenize("きょう")
    assert len(tokens) == 2
    assert [token.core for token in tokens] == ["きょ", "う"]
    assert [token.kind for token in tokens] == [TokenKind.KANA, TokenKind.KANA]


def test_katakana_with_long_vowel_mark() -> None:
    tokens = tokenize("ラーメン")
    assert [token.core for token in tokens] == ["ラー", "メ", "ン"]


def test_hangul_per_syllable() -> None:
    tokens = tokenize("한국어")
    assert [(token.core, token.kind) for token in tokens] == [
        ("한", TokenKind.HANGUL),
        ("국", TokenKind.HANGUL),
        ("어", TokenKind.HANGUL),
    ]


def test_kind_of_first_token() -> None:
    assert kind_of("你好") is TokenKind.HAN
    assert kind_of("hello") is TokenKind.WORD
    assert kind_of("ラーメン") is TokenKind.KANA
    assert kind_of("한국") is TokenKind.HANGUL
    assert kind_of("……") is TokenKind.NONE
    assert kind_of("") is TokenKind.NONE


def test_normalize_core_nfkc_and_casefold() -> None:
    assert normalize_core("ＡＢＣ") == "abc"
    assert normalize_core("ＡＢＣ") == normalize_core("abc")
    assert normalize_core("Ｉ") == normalize_core("i")


@pytest.mark.parametrize(
    "raw",
    [
        "我是誰",
        "hello world",
        "我 love 你!",
        "(附)註……",
        "don't stop 3.14",
        "rock-n-roll",
        "……",
        "きょう ラーメン",
        "한국어 노래",
        "  leading and trailing  ",
        "a\t\tb   c",
        "[男] 有標記的行?",
        "混合han한ラ漢123",
    ],
)
def test_token_texts_concatenate_to_normalized_line(raw: str) -> None:
    normalized = " ".join(raw.split())
    tokens = tokenize(raw)
    assert "".join(token.text for token in tokens) == normalized


def test_reading_annotations_and_escapes_are_not_part_of_the_text() -> None:
    assert "".join(token.text for token in tokenize("重{ㄔㄨㄥˊ}複了一次")) == "重複了一次"
    assert "".join(token.text for token in tokenize(r"\{literal\} braces")) == "{literal} braces"


def test_brace_after_whitespace_or_unclosed_is_literal() -> None:
    assert [token.ruby for token in tokenize("a {b}")] == [None, None]
    assert "".join(token.text for token in tokenize("重{沒有結尾")) == "重{沒有結尾"


def test_opening_quote_before_latin_word_and_trailing_opening_bracket() -> None:
    assert [token.text for token in tokenize("say “hello” (")] == ["say ", "“hello” ("]


def test_combining_mark_stays_with_its_base_character() -> None:
    tokens = tokenize("cafe\u0301 ole")
    assert [token.core for token in tokens] == ["caf\u00e9", "ole"]


def test_script_predicates() -> None:
    assert is_han("我") and is_han("々") and is_han("〇") and is_han("𠀀")
    assert not is_han("a") and not is_han("あ") and not is_han("한")
    assert is_kana("あ") and is_kana("ア") and is_kana("ー") and is_kana("ｱ")
    assert not is_kana("我") and not is_kana("a")
    assert is_hangul("한") and not is_hangul("ㄱ") and not is_hangul("我")
