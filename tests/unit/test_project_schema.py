from __future__ import annotations

import pytest
from pydantic import ValidationError

from karaforge.project.schema import (
    Line,
    Project,
    Render,
    Token,
    default_singers,
)


def make_token(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {"text": "你"}
    base.update(changes)
    return base


def test_token_times_must_be_set_together() -> None:
    with pytest.raises(ValidationError):
        Token.model_validate({"text": "你", "start_ms": 100})
    with pytest.raises(ValidationError):
        Token.model_validate({"text": "你", "end_ms": 200})


def test_token_end_must_not_be_before_start() -> None:
    with pytest.raises(ValidationError):
        Token.model_validate({"text": "你", "start_ms": 200, "end_ms": 100})


def test_locked_token_requires_times() -> None:
    with pytest.raises(ValidationError):
        Token.model_validate({"text": "你", "locked": True})
    token = Token.model_validate({"text": "你", "start_ms": 10, "end_ms": 20, "locked": True})
    assert token.locked is True


def test_confidence_must_be_between_0_and_1() -> None:
    with pytest.raises(ValidationError):
        Token.model_validate({"text": "你", "confidence": 1.5})
    with pytest.raises(ValidationError):
        Token.model_validate({"text": "你", "confidence": -0.1})
    token = Token.model_validate({"text": "你", "confidence": 0.93})
    assert token.confidence == pytest.approx(0.93)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Token.model_validate({"text": "你", "stars": 5})
    with pytest.raises(ValidationError):
        Project.model_validate({"schema_version": 1, "nope": True})


def test_line_derived_properties() -> None:
    line = Line(
        id="L001",
        tokens=[
            Token.model_validate({"text": "你", "start_ms": 100, "end_ms": 200}),
            Token.model_validate({"text": "好", "start_ms": 300, "end_ms": 400}),
        ],
    )
    assert line.text == "你好"
    assert line.start_ms == 100
    assert line.end_ms == 400
    assert line.is_timed is True


def test_line_without_times_is_not_timed() -> None:
    line = Line(id="L001", tokens=[Token(text="你"), Token(text="好")])
    assert line.text == "你好"
    assert line.start_ms is None
    assert line.end_ms is None
    assert line.is_timed is False


def test_empty_line_is_not_timed() -> None:
    line = Line(id="L001")
    assert line.text == ""
    assert line.start_ms is None
    assert line.end_ms is None
    assert line.is_timed is False


def test_duplicate_singer_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate(
            {
                "singers": [
                    {"id": "m", "label": "男"},
                    {"id": "m", "label": "合"},
                ]
            }
        )


def test_duplicate_line_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate(
            {
                "lines": [
                    {"id": "L001", "tokens": [{"text": "你"}]},
                    {"id": "L001", "tokens": [{"text": "好"}]},
                ]
            }
        )


def test_line_referencing_unknown_singer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate({"lines": [{"id": "L001", "singer": "ghost", "tokens": []}]})


def test_singer_and_line_lookup() -> None:
    project = Project()
    assert project.singer("f").label == "女"
    with pytest.raises(KeyError):
        project.singer("nope")
    project.lines.append(Line(id="L001", tokens=[Token(text="你")]))
    assert project.line("L001").tokens[0].text == "你"
    with pytest.raises(KeyError):
        project.line("L999")


def test_has_lyrics_and_is_aligned() -> None:
    empty = Project()
    assert empty.has_lyrics is False
    assert empty.is_aligned is False

    untimed = Project(lines=[Line(id="L001", tokens=[Token(text="你")])])
    assert untimed.has_lyrics is True
    assert untimed.is_aligned is False

    aligned = Project(
        lines=[
            Line(
                id="L001",
                tokens=[
                    Token(text="你", start_ms=100, end_ms=200),
                    Token(text="好", start_ms=200, end_ms=300),
                ],
            )
        ]
    )
    assert aligned.is_aligned is True


def test_render_resolution_must_be_even_and_at_least_16() -> None:
    for resolution in [(1919, 1080), (1920, 1081), (14, 1080), (1920, 15)]:
        with pytest.raises(ValidationError):
            Render(resolution=resolution)
    assert Render(resolution=(1280, 720)).resolution == (1280, 720)


def test_default_singers() -> None:
    singers = default_singers()
    assert [(singer.id, singer.label, singer.theme_slot) for singer in singers] == [
        ("m", "男", "male"),
        ("f", "女", "female"),
        ("all", "合", "duet"),
    ]


def test_spec_example_round_trips_unchanged() -> None:
    """The example document from SPEC §4.2 loads and dumps back to exactly the same JSON."""
    document: dict[str, object] = {
        "schema_version": 1,
        "revision": 42,
        "meta": {
            "title": "",
            "artist": "",
            "lyricist": "",
            "composer": "",
            "language": "zh-TW",
            "duration_ms": 0,
        },
        "media": {
            "source": "media/source.mp4",
            "audio": "media/audio.wav",
            "vocals": "media/vocals.wav",
            "instrumental": "media/instrumental.wav",
            "has_video": True,
        },
        "analysis": {"tempo_bpm": 92.0, "beats_ms": [], "vocal_regions": [[1200, 15800]]},
        "singers": [
            {"id": "m", "label": "男", "theme_slot": "male"},
            {"id": "f", "label": "女", "theme_slot": "female"},
            {"id": "all", "label": "合", "theme_slot": "duet"},
        ],
        "lines": [
            {
                "id": "L001",
                "singer": "m",
                "paragraph": 0,
                "tokens": [
                    {
                        "text": "我",
                        "start_ms": 15230,
                        "end_ms": 15610,
                        "ruby": "ㄨㄛˇ",
                        "ruby_source": "auto",
                        "confidence": 0.93,
                        "locked": False,
                        "source": "auto",
                    }
                ],
            }
        ],
        "style": {"theme": "classic-ktv", "overrides": {}},
        "render": {
            "resolution": [1920, 1080],
            "fps": 30,
            "background": {"type": "video"},
        },
    }
    project = Project.model_validate(document)
    dumped = project.model_dump(mode="json", exclude_none=True)
    assert dumped == document
    assert Project.model_validate(dumped) == project
