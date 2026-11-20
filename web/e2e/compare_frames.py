"""Compare what the editor's preview shows with a frame of the exported video.

Both pictures are reduced to the same measurements: where the *sung* colour and the *unsung*
colour appear, as fractions of the picture size.  The preview is a browser screenshot of the
preview area; the video frame is taken at the same media time.  The script prints the
measurements as JSON; the browser test asserts on them.

Usage::

    python compare_frames.py --preview shot.png --video out.mp4 --time 6.2 \
        --sung "#2F7BFF" --unsung "#FFFFFF"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import numpy.typing as npt

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "engine")]

from karaforge.layout.theme import rgb_of  # noqa: E402
from karaforge.tools import ffmpeg  # noqa: E402

Frame = npt.NDArray[np.uint8]


def decode(source: Path, time_s: float | None, work: Path) -> Frame:
    """One RGB picture: a still image, or the video frame shown at ``time_s``."""
    info = ffmpeg.probe(source)
    stream = info.video
    if stream is None or not stream.width or not stream.height:
        raise SystemExit(f"{source} has no picture")
    shutil.copyfile(source, work / f"input{source.suffix}")
    arguments = ["-i", f"input{source.suffix}"]
    if time_s is not None:
        rate = stream.frame_rate or 30.0
        arguments += ["-vf", f"select='eq(n\\,{round(time_s * rate)})'", "-fps_mode", "passthrough"]
    arguments += ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "frame.rgb"]
    ffmpeg.run_ffmpeg(arguments, cwd=work)
    raw = np.frombuffer((work / "frame.rgb").read_bytes(), dtype=np.uint8)
    return raw.reshape(stream.height, stream.width, 3)


def measure(frame: Frame, color: str, tolerance: int) -> dict[str, float] | None:
    """Bounding box of the pixels close to ``color``, as fractions of the picture size."""
    target = np.array(rgb_of(color), dtype=np.int16)
    mask = np.abs(frame.astype(np.int16) - target).max(axis=2) <= tolerance
    if int(mask.sum()) < 20:
        return None
    rows = np.flatnonzero(mask.any(axis=1))
    columns = np.flatnonzero(mask.any(axis=0))
    height, width = mask.shape
    return {
        "left": float(columns[0] / width),
        "right": float((columns[-1] + 1) / width),
        "top": float(rows[0] / height),
        "bottom": float((rows[-1] + 1) / height),
        "share": float(mask.mean()),
    }


def main() -> int:
    """Print the measurements of both pictures."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--time", type=float, required=True)
    parser.add_argument("--sung", required=True)
    parser.add_argument("--unsung", required=True)
    parser.add_argument("--tolerance", type=int, default=56)
    arguments = parser.parse_args()
    result: dict[str, object] = {}
    for name, source, time_s in (
        ("preview", arguments.preview, None),
        ("video", arguments.video, arguments.time),
    ):
        # ffmpeg (possibly a container) must be able to see the folder: work next to the file.
        work = Path(tempfile.mkdtemp(prefix="compare-", dir=source.resolve().parent))
        try:
            frame = decode(source.resolve(), time_s, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        result[name] = {
            "size": [int(frame.shape[1]), int(frame.shape[0])],
            "sung": measure(frame, arguments.sung, arguments.tolerance),
            "unsung": measure(frame, arguments.unsung, arguments.tolerance),
        }
    print(json.dumps(result))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
