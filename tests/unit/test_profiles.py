from __future__ import annotations

from typing import Any

import pytest

from karaforge.errors import PipelineError
from karaforge.pipeline.profiles import get_profile, parse_overrides, profile_names


def test_profile_names_include_builtins() -> None:
    names = profile_names()
    assert "cpu-lite" in names
    assert "balanced" in names
    assert "gpu-quality" in names


def test_get_profile_defaults_to_balanced() -> None:
    assert get_profile().name == "balanced"


def test_get_profile_unknown_name_raises() -> None:
    with pytest.raises(PipelineError):
        get_profile("nope")


def test_get_profile_returns_independent_copies() -> None:
    first = get_profile()
    first.align.onset_snap_ms = 123
    second = get_profile()
    assert second.align.onset_snap_ms == 60
    assert second.align is not first.align


def test_builtin_profiles_name_matches_key() -> None:
    for name in profile_names():
        assert get_profile(name).name == name


def test_with_overrides_applies_dotted_key_without_touching_original() -> None:
    profile = get_profile("balanced")
    adjusted = profile.with_overrides({"align.onset_snap_ms": 80})
    assert adjusted.align.onset_snap_ms == 80
    assert profile.align.onset_snap_ms == 60
    assert adjusted is not profile


def test_with_overrides_unknown_key_raises() -> None:
    profile = get_profile()
    bad_keys = ("align.nope", "nope.x", "align")
    for key in bad_keys:
        with pytest.raises(PipelineError):
            profile.with_overrides({key: 1})


def test_with_overrides_invalid_value_raises() -> None:
    profile = get_profile()
    bad_values: tuple[tuple[str, Any], ...] = (
        ("align.min_token_ms", 0),
        ("align.coarse", "bogus"),
    )
    for key, value in bad_values:
        with pytest.raises(PipelineError):
            profile.with_overrides({key: value})


def test_with_overrides_accepts_valid_values() -> None:
    profile = get_profile()
    adjusted = profile.with_overrides(
        {"align.min_token_ms": 1, "align.coarse": "regions", "asr.beam_size": 3}
    )
    assert adjusted.align.min_token_ms == 1
    assert adjusted.align.coarse == "regions"
    assert adjusted.asr.beam_size == 3


def test_parse_overrides_types() -> None:
    parsed = parse_overrides(["a.b=1", "c.d=true", "e.f=0.5", "g.h=text", "i.j=off"])
    assert parsed == {"a.b": 1, "c.d": True, "e.f": 0.5, "g.h": "text", "i.j": False}
    assert isinstance(parsed["a.b"], int)
    assert isinstance(parsed["c.d"], bool)
    assert isinstance(parsed["e.f"], float)
    assert isinstance(parsed["g.h"], str)
    assert isinstance(parsed["i.j"], bool)


def test_parse_overrides_malformed_items_raise() -> None:
    for item in ("a.b", "=1", "  =1", "a.b"):
        with pytest.raises(PipelineError):
            parse_overrides([item])


def test_parse_overrides_empty_value_becomes_empty_string() -> None:
    assert parse_overrides(["a.b="]) == {"a.b": ""}


def test_parse_overrides_typical_override() -> None:
    assert parse_overrides(["align.onset_snap_ms=80"]) == {"align.onset_snap_ms": 80}
