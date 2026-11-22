"""Helpers shared by the tests: builders for alignment inputs and explicit test doubles.

Nothing here stands in for a real model in a benchmark or an integration test.  The classes
named ``Fake…`` exist so that the *logic around* the models (windowing, anchors, refinement)
can be tested deterministically and without weights.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

import numpy as np
import numpy.typing as npt

from karaforge.adapters.base import AdapterInfo, AlignRequest, AsrWord, UnitTiming
from karaforge.align.coarse import LyricLine
from karaforge.align.features import HOP_S, VocalFeatures
from karaforge.audio.io import MODEL_RATE
from karaforge.layout.fonts import default_library
from karaforge.layout.plan import PlanLine, RenderPlan
from karaforge.layout.theme import rgb_of
from karaforge.pipeline.stage import link_or_copy
from karaforge.project import Line, Project, Token
from karaforge.text.romanize import romanize_tokens
from karaforge.text.tokenize import tokenize
from karaforge.tools import ffmpeg

Frame = npt.NDArray[np.uint8]
"""An RGB frame of shape ``(height, width, 3)``."""


def lyric_line(
    line_id: str,
    text: str,
    locked: dict[int, tuple[float, float]] | None = None,
    hint: tuple[float, float | None] | None = None,
) -> LyricLine:
    """Build a :class:`LyricLine` from plain text; ``locked`` maps token index to times."""
    tokens = tokenize(text)
    cores = [token.core for token in tokens]
    kinds = [token.kind for token in tokens]
    readings = romanize_tokens(cores, kinds, [token.ruby for token in tokens])
    locks = locked or {}
    return LyricLine(
        id=line_id,
        cores=tuple(cores),
        kinds=tuple(kinds),
        readings=tuple(readings),
        locked=tuple(locks.get(index) for index in range(len(tokens))),
        hint=hint,
    )


def sung_words(text: str, start_s: float, step_s: float = 0.4) -> list[AsrWord]:
    """A transcript in which every token of ``text`` is one word, evenly spaced from ``start_s``."""
    result: list[AsrWord] = []
    for index, token in enumerate(token for token in tokenize(text) if token.core):
        begin = start_s + index * step_s
        result.append(AsrWord(token.core, begin, begin + step_s * 0.9, 0.9))
    return result


def make_features(
    duration_s: float,
    active: Sequence[tuple[float, float]],
    onsets: Sequence[float] = (),
    *,
    loud_db: float = -20.0,
    quiet_db: float = -70.0,
) -> VocalFeatures:
    """Features of an imaginary vocal stem that is loud exactly inside ``active``."""
    frames = round(duration_s / HOP_S)
    energy = np.full(frames, quiet_db, dtype=np.float32)
    for start, end in active:
        energy[round(start / HOP_S) : round(end / HOP_S)] = loud_db
    return VocalFeatures(
        energy_db=energy,
        flatness=np.full(frames, 0.1, dtype=np.float32),
        onset_strength=np.zeros(frames, dtype=np.float32),
        onsets_s=np.asarray(sorted(onsets), dtype=np.float64),
        onset_peaks=np.ones(len(onsets), dtype=np.float32),
        regions_s=tuple((float(start), float(end)) for start, end in active),
        noise_floor_db=quiet_db,
        active_threshold_db=(loud_db + quiet_db) / 2.0,
    )


class FakeAligner:
    """Test double for a forced aligner: spreads the units evenly over the window it is given.

    It records every request, so tests can assert on the windows and context the fine pass
    hands to an aligner.  ``lead_s`` shifts every start, to imitate a systematic aligner bias.
    """

    def __init__(self, lead_s: float = 0.0, score: float = 0.8) -> None:
        self.requests: list[AlignRequest] = []
        self.lead_s = lead_s
        self.score = score

    @property
    def info(self) -> AdapterInfo:
        """Self-description of the test double."""
        return AdapterInfo(
            name="fake-uniform",
            version=f"test-{id(self):x}",
            license="n/a",
            languages=("*",),
            devices=("cpu",),
            memory_mb=0,
        )

    def align(self, request: AlignRequest) -> list[UnitTiming]:
        """Place unit ``i`` of ``n`` at ``i / n`` of the window."""
        self.requests.append(request)
        duration = request.audio.size / MODEL_RATE
        count = len(request.units)
        step = duration / count if count else 0.0
        return [
            UnitTiming(
                start_s=max(0.0, index * step + self.lead_s),
                end_s=min(duration, (index + 1) * step + self.lead_s),
                score=self.score,
            )
            for index in range(count)
        ]


# --------------------------------------------------------------------------- project builders


def timed_line(
    line_id: str,
    text: str,
    start_ms: int,
    token_ms: int = 400,
    *,
    singer: str = "m",
    paragraph: int = 0,
    gap_ms: int = 0,
) -> Line:
    """A lyric line whose tokens are sung back to back, ``token_ms`` each, from ``start_ms``."""
    tokens: list[Token] = []
    cursor = start_ms
    for item in tokenize(text):
        tokens.append(
            Token(
                text=item.text,
                start_ms=cursor,
                end_ms=cursor + token_ms,
                ruby=item.ruby,
                ruby_source="manual" if item.ruby else None,
                confidence=0.9,
            )
        )
        cursor += token_ms + gap_ms
    return Line(id=line_id, singer=singer, paragraph=paragraph, tokens=tokens)


def song_project(
    lines: Sequence[Line],
    *,
    resolution: tuple[int, int] = (1920, 1080),
    theme: str = "classic-ktv",
    title: str = "測試歌曲",
    duration_ms: int = 120_000,
) -> Project:
    """A project with the given lines, ready for layout."""
    project = Project(lines=list(lines))
    project.meta.title = title
    project.meta.artist = "某歌手"
    project.meta.duration_ms = duration_ms
    project.render.resolution = resolution
    project.style.theme = theme
    return project


# ------------------------------------------------------------------------------ rendering


def _frames_from_raw(path: Path, width: int, height: int, count: int) -> list[Frame]:
    data = np.fromfile(path, dtype=np.uint8)
    size = width * height * 3
    if data.size < size * count:
        raise AssertionError(f"expected {count} frames, ffmpeg produced {data.size // size}")
    return [
        data[index * size : (index + 1) * size].reshape(height, width, 3) for index in range(count)
    ]


def _select(times_s: Sequence[float], fps: float) -> str:
    frames = sorted({round(time * fps) for time in times_s})
    return "+".join(f"eq(n\\,{frame})" for frame in frames)


def render_frames(
    script: str,
    plan: RenderPlan,
    times_s: Sequence[float],
    work: Path,
    *,
    fps: float = 50.0,
    background: str = "#404040",
) -> list[Frame]:
    """Draw an ASS script with ffmpeg + libass and return the frames at ``times_s`` (ascending).

    The subtitles are composited onto an RGB canvas and the frames are returned without any
    video compression, so pixel colours are exact up to anti-aliasing.
    """
    (work / "fonts").mkdir(parents=True, exist_ok=True)
    library = default_library()
    for font in plan.fonts:
        face = library.find(font.family)
        link_or_copy(face.path, work / "fonts" / face.path.name)
    (work / "subs.ass").write_text(script, encoding="utf-8")
    duration = max(times_s) + 1.0
    color = background.lstrip("#")
    ffmpeg.run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{color}:s={plan.width}x{plan.height}:r={fps:g}:d={duration:.3f}",
            "-vf",
            # Composite in RGB: in the source's native 4:2:0 format the half-resolution
            # chroma would smear colours across glyph edges.
            f"format=rgb24,ass=subs.ass:fontsdir=fonts,select='{_select(times_s, fps)}'",
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "frames.rgb",
        ],
        cwd=work,
    )
    return _frames_from_raw(work / "frames.rgb", plan.width, plan.height, len(set(times_s)))


def grab_frames(video: Path, times_s: Sequence[float], work: Path, *, fps: float) -> list[Frame]:
    """Decode the frames of a video file at ``times_s`` (ascending) as RGB arrays."""
    info = ffmpeg.probe(video)
    stream = info.video
    assert stream is not None and stream.width and stream.height
    link_or_copy(video, work / f"input{video.suffix}")
    ffmpeg.run_ffmpeg(
        [
            "-i",
            f"input{video.suffix}",
            "-vf",
            f"select='{_select(times_s, fps)}'",
            "-fps_mode",
            "passthrough",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "grabbed.rgb",
        ],
        cwd=work,
    )
    return _frames_from_raw(work / "grabbed.rgb", stream.width, stream.height, len(set(times_s)))


def color_mask(frame: Frame, color: str, tolerance: int = 48) -> npt.NDArray[np.bool_]:
    """Pixels of ``frame`` within ``tolerance`` (per channel) of ``#RRGGBB``."""
    target = np.array(rgb_of(color), dtype=np.int16)
    difference = np.abs(frame.astype(np.int16) - target)
    return np.asarray(difference.max(axis=2) <= tolerance)


def fill_position(plan_line: PlanLine, time_ms: float) -> float:
    """Where the fill boundary of a planned line should be at ``time_ms`` (clip left if unsung)."""
    keys = plan_line.fill
    if not keys or time_ms < keys[0].time_ms:
        return plan_line.clip_left
    for earlier, later in pairwise(keys):
        if earlier.time_ms <= time_ms <= later.time_ms:
            if later.time_ms == earlier.time_ms:
                return later.x
            share = (time_ms - earlier.time_ms) / (later.time_ms - earlier.time_ms)
            return earlier.x + share * (later.x - earlier.x)
    return keys[-1].x


FAKE_YTDLP = Path(__file__).parent / "fixtures" / "fake_yt_dlp.py"


def install_fake_ytdlp(folder: Path, *, media: Path | None = None) -> dict[str, str]:
    """Put the test stand-in for yt-dlp (``fixtures/fake_yt_dlp.py``) into ``folder``.

    Returns the environment variables that make KaraForge use it; set them with
    ``monkeypatch.setenv``.  ``FAKE_YTDLP_LOG`` names the file that collects its command lines.
    """
    import sys

    folder.mkdir(parents=True, exist_ok=True)
    launcher = folder / "yt-dlp"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_YTDLP}" "$@"\n')
    launcher.chmod(0o755)
    variables = {"KARAFORGE_YTDLP": str(launcher), "FAKE_YTDLP_LOG": str(folder / "calls.jsonl")}
    if media is not None:
        variables["FAKE_YTDLP_MEDIA"] = str(media)
    return variables
