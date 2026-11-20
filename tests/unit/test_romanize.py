from __future__ import annotations

from karaforge.text.romanize import (
    han_readings,
    hangul_reading,
    kana_reading,
    normalize_reading,
    romanize_tokens,
    to_simplified,
    word_reading,
    zhuyin_to_pinyin,
)
from karaforge.text.tokenize import tokenize


def test_to_simplified() -> None:
    assert to_simplified("頭髮") == "头发"


def test_zhuyin_to_pinyin_syllables() -> None:
    assert zhuyin_to_pinyin("ㄔㄨㄥˊ") == "chong"
    assert zhuyin_to_pinyin("ㄨㄛˇ") == "wo"
    assert zhuyin_to_pinyin("ㄩㄝˋ") == "yue"
    assert zhuyin_to_pinyin("ㄒㄩㄥˊ") == "xiong"
    assert zhuyin_to_pinyin("ㄋㄩˇ") == "nv"
    assert zhuyin_to_pinyin("ㄧ") == "yi"
    assert zhuyin_to_pinyin("ㄉㄜ˙") == "de"


def test_zhuyin_to_pinyin_unknown_returns_none() -> None:
    assert zhuyin_to_pinyin("ㄗㄨㄛㄋㄍ") is None
    assert zhuyin_to_pinyin("hello") is None


def test_normalize_reading_pinyin_variants() -> None:
    assert normalize_reading("chóng") == "chong"
    assert normalize_reading("chong2") == "chong"
    assert normalize_reading("ㄔㄨㄥˊ") == "chong"


def test_normalize_reading_umlaut_becomes_v() -> None:
    assert normalize_reading("nǚ") == "nv"


def test_normalize_reading_invalid_returns_none() -> None:
    assert normalize_reading("") is None
    assert normalize_reading("???") is None


def test_han_readings_resolves_polyphony_via_phrase() -> None:
    assert han_readings("重複") == ["chong", "fu"]
    assert han_readings("銀行") == ["yin", "hang"]
    assert han_readings("音樂") == ["yin", "yue"]


def test_han_readings_empty_run() -> None:
    assert han_readings("") == []


def test_kana_reading() -> None:
    assert kana_reading("きょ") == "kyo"
    assert kana_reading("しゃ") == "sha"
    assert kana_reading("ラー") == "ra"
    assert kana_reading("ん") == "n"


def test_hangul_reading() -> None:
    assert hangul_reading("한") == "han"
    assert hangul_reading("국") == "guk"
    assert hangul_reading("사") == "sa"


def test_word_reading_strips_accents_and_punctuation() -> None:
    assert word_reading("Café") == "cafe"
    assert word_reading("I'm") == "im"
    assert word_reading("3D") == "3d"


def test_romanize_tokens_chinese_line() -> None:
    tokens = tokenize("他還是重複了一次")
    result = romanize_tokens([t.core for t in tokens], [t.kind for t in tokens])
    assert result == ["ta", "hai", "shi", "chong", "fu", "le", "yi", "ci"]


def test_romanize_tokens_manual_reading_wins() -> None:
    tokens = tokenize("他還是重{ㄓㄨㄥˋ}複")
    cores = [token.core for token in tokens]
    kinds = [token.kind for token in tokens]
    manual = [token.ruby for token in tokens]
    result = romanize_tokens(cores, kinds, manual)
    assert result == ["ta", "hai", "shi", "zhong", "fu"]
    assert result[3] == "zhong"


def test_romanize_tokens_mixed_chinese_english() -> None:
    tokens = tokenize("我愛 baby")
    result = romanize_tokens([t.core for t in tokens], [t.kind for t in tokens])
    assert result == ["wo", "ai", "baby"]


def test_romanize_tokens_punctuation_token_is_empty() -> None:
    tokens = tokenize("……")
    assert len(tokens) == 1
    assert tokens[0].kind.value == "none"
    result = romanize_tokens([tokens[0].core], [tokens[0].kind])
    assert result == [""]


def test_romanize_tokens_korean_and_english() -> None:
    tokens = tokenize("한국 song")
    result = romanize_tokens([t.core for t in tokens], [t.kind for t in tokens])
    assert result == ["han", "guk", "song"]


def test_romanize_tokens_japanese() -> None:
    tokens = tokenize("ありがとう")
    result = romanize_tokens([t.core for t in tokens], [t.kind for t in tokens])
    assert result == ["a", "ri", "ga", "to", "u"]
