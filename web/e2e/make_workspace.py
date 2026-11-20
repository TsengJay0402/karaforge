"""Build the workspace the browser tests run against.

Two ready-made projects, without running any model:

``demo``
    The synthetic test song from ``tests/fixtures`` with its ground-truth timing as the
    token times.  The "stems" are copies of the mix — good enough for an editor test.
``clip``
    A short generated test-pattern video with two timed lines, for everything that needs a
    picture (video preview, thumbnail, MP4 export).

Usage: ``python make_workspace.py <workspace folder>`` (needs ffmpeg, like the engine).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "engine")]

from karaforge.pipeline import get_profile  # noqa: E402
from karaforge.project import ProjectStore, Token  # noqa: E402
from karaforge.project.create import create_project  # noqa: E402
from karaforge.stages.standard import run_pipeline  # noqa: E402
from karaforge.tools import ffmpeg  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "songs" / "zh-2000"


def stand_in_stems(store: ProjectStore) -> None:
    """Use the decoded mix as both stems (no separation model in the browser tests)."""
    for name in ("vocals.wav", "instrumental.wav"):
        shutil.copyfile(store.paths.media / "audio.wav", store.paths.media / name)
    project = store.load()
    project.media.vocals = "media/vocals.wav"
    project.media.instrumental = "media/instrumental.wav"
    store.save(project)


def make_demo(workspace: Path) -> None:
    """The fixture song with its ground-truth timing."""
    store = create_project(
        FIXTURE / "mix_snr10.mp3",
        workspace / "demo.kfproj",
        lyrics=FIXTURE / "lyrics.txt",
        language="zh-TW",
        title="示範歌曲",
        artist="KaraForge",
    )
    run_pipeline(store, profile=get_profile("cpu-lite"), targets=("ingest",))
    stand_in_stems(store)
    truth = json.loads((FIXTURE / "truth.json").read_text(encoding="utf-8"))
    project = store.load()
    onsets: list[int] = []
    for line, expected in zip(project.lines, truth["lines"], strict=True):
        pairs = zip(line.tokens, expected["tokens"], strict=True)
        for index, (token, reference) in enumerate(pairs):
            # A few doubtful tokens, so that the confidence colours have something to show.
            confidence = 0.35 if index % 7 == 3 else 0.7 if index % 5 == 2 else 0.95
            line.tokens[index] = Token(
                text=token.text,
                start_ms=int(reference["start_ms"]),
                end_ms=int(reference["end_ms"]),
                confidence=confidence,
            )
            onsets.append(int(reference["start_ms"]))
    store.save(project)
    analysis = {"onsets_ms": sorted(onsets), "regions_ms": [], "beats_ms": [], "tempo_bpm": None}
    (store.paths.media / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")


def make_clip(workspace: Path) -> None:
    """A generated eight-second video with two hand-timed lines."""
    scratch = workspace / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    ffmpeg.run_ffmpeg(
        [
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=8",
            "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=8",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ac", "2", "-shortest", "clip.mp4",
        ],
        cwd=scratch,
    )  # fmt: skip
    lyrics = scratch / "lyrics.txt"
    lyrics.write_text("# title: 測試影片\n[男] 一二三四五\n[女] hello world\n", encoding="utf-8")
    store = create_project(scratch / "clip.mp4", workspace / "clip.kfproj", lyrics=lyrics)
    run_pipeline(store, profile=get_profile("cpu-lite"), targets=("ingest",))
    stand_in_stems(store)
    project = store.load()
    project.render.resolution = (640, 360)
    starts = ([1000, 1500, 2000, 2500, 3000], [4500, 5200])
    lengths = (500, 700)
    for line, line_starts, length in zip(project.lines, starts, lengths, strict=True):
        for index, start in enumerate(line_starts):
            line.tokens[index] = Token(
                text=line.tokens[index].text, start_ms=start, end_ms=start + length, confidence=0.95
            )
    store.save(project)
    shutil.rmtree(scratch)


def main() -> int:
    """Create the workspace given on the command line (replacing an existing one)."""
    workspace = Path(sys.argv[1]).resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    make_demo(workspace)
    make_clip(workspace)
    print(f"workspace ready: {workspace}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
