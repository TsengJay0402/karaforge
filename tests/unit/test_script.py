from __future__ import annotations

import pytest

from karaforge.text.script import convert_script, script_config


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("zh-TW", "s2tw"),
        ("zh", "s2tw"),
        ("zh-Hant", "s2tw"),
        ("ZH_tw", "s2tw"),
        ("zh-HK", "s2hk"),
        ("zh-MO", "s2hk"),
        ("zh-CN", "t2s"),
        ("zh-Hans", "t2s"),
        ("zh-SG", "t2s"),
        ("yue", "s2tw"),
        ("en", None),
        ("ja", None),
        ("", None),
    ],
)
def test_script_config(language: str, expected: str | None) -> None:
    assert script_config(language) == expected


def test_convert_script_to_traditional_for_zh_tw() -> None:
    assert convert_script("车窗上的雨滴", "zh-TW") == "車窗上的雨滴"


def test_convert_script_to_simplified_for_zh_cn() -> None:
    assert convert_script("車窗", "zh-CN") == "车窗"


def test_convert_script_leaves_non_chinese_text_unchanged() -> None:
    assert convert_script("hello 世界", "en") == "hello 世界"


def test_convert_script_empty_text_stays_empty() -> None:
    assert convert_script("", "zh-TW") == ""


def test_convert_script_keeps_mainland_vocabulary() -> None:
    # Only character forms change: ``s2tw``, not the phrase-level ``s2twp``.
    assert convert_script("软件", "zh-TW") == "軟件"


def test_convert_script_preserves_character_count() -> None:
    assert len(convert_script("我们一起唱歌", "zh-TW")) == 6
