from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from karaforge.errors import ThemeError
from karaforge.layout.theme import (
    Theme,
    ass_color,
    ass_color_tag,
    dump_theme,
    list_themes,
    load_theme,
    load_theme_file,
    rgb_of,
)

BUILTIN_THEMES = ("classic-ktv", "pop-round", "clean-center", "zhuyin-learner")


def test_ass_color_opaque() -> None:
    assert ass_color("#FF8000") == "&H000080FF"


def test_ass_color_alpha_is_inverted() -> None:
    result = ass_color("#FF800080")
    assert result == "&H7F0080FF"  # alpha 0x80 (half transparent) becomes 0x7F
    assert result[2:4] == "7F"


def test_ass_color_tag_is_bgr() -> None:
    assert ass_color_tag("#FF8000") == "&H0080FF&"


def test_rgb_of_components() -> None:
    assert rgb_of("#102030") == (16, 32, 48)


def test_ass_color_invalid_string_raises() -> None:
    for bad in ("FF8000", "#FFF", "#GGHHII", "red", ""):
        with pytest.raises(ValueError):
            ass_color(bad)


def test_ass_color_tag_and_rgb_of_invalid_string_raise() -> None:
    with pytest.raises(ValueError):
        ass_color_tag("nope")
    with pytest.raises(ValueError):
        rgb_of("nope")


def test_theme_defaults() -> None:
    theme = Theme(name="x")
    assert theme.name == "x"
    assert theme.title == ""
    assert theme.reference_height == 1080
    assert theme.font.size == pytest.approx(84.0)
    assert theme.colors.slots["male"].fill == "#2F7BFF"
    assert theme.layout.rows[0].y == pytest.approx(0.74)
    assert theme.background.color == "#12141C"


def test_theme_rejects_invalid_color() -> None:
    with pytest.raises(ValidationError):
        Theme.model_validate({"name": "x", "colors": {"shadow": "black"}})


def test_with_overrides_font_size() -> None:
    theme = Theme(name="x")
    adjusted = theme.with_overrides({"font.size": 96})
    assert adjusted.font.size == 96
    assert theme.font.size == pytest.approx(84.0)
    assert adjusted is not theme


def test_with_overrides_slot_color() -> None:
    theme = Theme(name="x")
    adjusted = theme.with_overrides({"colors.slots.male.fill": "#00AAFF"})
    assert adjusted.colors.slots["male"].fill == "#00AAFF"
    assert theme.colors.slots["male"].fill == "#2F7BFF"


def test_with_overrides_row_position() -> None:
    theme = Theme(name="x")
    adjusted = theme.with_overrides({"layout.rows.0.y": 0.5})
    assert adjusted.layout.rows[0].y == pytest.approx(0.5)
    assert theme.layout.rows[0].y == pytest.approx(0.74)


def test_with_overrides_empty_dict_returns_same_object() -> None:
    theme = Theme(name="x")
    assert theme.with_overrides({}) is theme


def test_with_overrides_unknown_key_raises() -> None:
    theme = Theme(name="x")
    with pytest.raises(ThemeError):
        theme.with_overrides({"font.nope": 1})


def test_with_overrides_invalid_value_raises() -> None:
    theme = Theme(name="x")
    with pytest.raises(ThemeError):
        theme.with_overrides({"font.size": -1})


def test_with_overrides_can_add_a_new_slot() -> None:
    theme = Theme(name="x")
    adjusted = theme.with_overrides(
        {"colors.slots.guest": {"fill": "#112233", "outline": "#FFFFFF"}}
    )
    assert adjusted.colors.slots["guest"].fill == "#112233"
    assert adjusted.colors.slots["guest"].outline == "#FFFFFF"
    assert "guest" not in theme.colors.slots


def test_slot_known_name() -> None:
    theme = Theme(name="x")
    assert theme.slot("male") is theme.colors.slots["male"]
    assert theme.slot("male").fill == "#2F7BFF"


def test_slot_unknown_name_falls_back_to_duet() -> None:
    theme = Theme(name="x")
    fallback = theme.slot("nobody")
    assert fallback is theme.colors.slots["duet"]
    assert fallback.fill == "#35D05B"


def test_list_themes_with_user_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    names = list_themes()
    for builtin in BUILTIN_THEMES:
        assert builtin in names


def test_user_theme_is_listed_and_loadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    themes_dir = tmp_path / "themes"
    themes_dir.mkdir()
    (themes_dir / "mine.yaml").write_text("name: mine\nfont:\n  size: 70\n", encoding="utf-8")
    names = list_themes()
    assert "mine" in names
    for builtin in BUILTIN_THEMES:
        assert builtin in names
    theme = load_theme("mine")
    assert theme.name == "mine"
    assert theme.font.size == pytest.approx(70.0)


def test_load_theme_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    with pytest.raises(ThemeError):
        load_theme("不存在")


def test_load_theme_file_rejects_non_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ThemeError):
        load_theme_file(path)


def test_load_theme_file_rejects_broken_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    path = tmp_path / "broken.yaml"
    path.write_text("name: [unclosed\n  : :\n", encoding="utf-8")
    with pytest.raises(ThemeError):
        load_theme_file(path)


def test_load_theme_file_uses_filename_as_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    path = tmp_path / "unnamed.yaml"
    path.write_text("title: just a title\n", encoding="utf-8")
    theme = load_theme_file(path)
    assert theme.name == "unnamed"


def test_dump_theme_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    theme = Theme.model_validate({"name": "roundtrip", "font": {"size": 91}})
    path = tmp_path / "roundtrip.yaml"
    path.write_text(dump_theme(theme), encoding="utf-8")
    assert load_theme_file(path) == theme


def test_builtin_themes_load_and_have_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KARAFORGE_HOME", str(tmp_path))
    for name in BUILTIN_THEMES:
        theme = load_theme(name)
        assert theme.name == name
        for slot in ("male", "female", "duet"):
            assert slot in theme.colors.slots
