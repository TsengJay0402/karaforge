"""A stand-in for yt-dlp in the tests: no network, canned answers.

It understands just enough of yt-dlp's command line for KaraForge: ``--version``,
``--dump-single-json`` (describe a video) and a download with ``--paths`` / ``--output``
(write ``media.wav``, reporting progress the way KaraForge asks yt-dlp to).

Environment:
    FAKE_YTDLP_MODE   ``video`` (default), ``music``, ``playlist``, ``live``, ``error``,
                      ``unsupported`` or ``slow`` (a download that takes long enough to cancel).
    FAKE_YTDLP_MEDIA  File to "download" (copied to ``media.wav``).
    FAKE_YTDLP_LOG    File that receives the command line, one JSON list per call.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _err(text: str) -> None:
    sys.stderr.write(text + "\n")


def _value(args: list[str], option: str) -> str | None:
    return args[args.index(option) + 1] if option in args else None


def main() -> int:
    args = sys.argv[1:]
    log = os.environ.get("FAKE_YTDLP_LOG")
    if log:
        with Path(log).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(args) + "\n")
    if args == ["--version"]:
        _out("2099.01.01")
        return 0
    mode = os.environ.get("FAKE_YTDLP_MODE", "video")
    url = args[-1]
    if mode == "unsupported":
        _err(f"ERROR: Unsupported URL: {url}")
        return 1
    if mode == "error":
        _err("WARNING: something harmless")
        _err("ERROR: [youtube] abc123: Video unavailable")
        return 1

    info: dict[str, object] = {
        "id": "abc123",
        "title": "晴天 (Official MV)",
        "uploader": "某歌手 - Topic",
        "duration": 269.5,
        "thumbnail": "https://example.com/thumb.jpg",
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
        "extractor_key": "Youtube",
        "filesize_approx": 3000,
        "requested_formats": [
            {"format_id": "137", "vcodec": "avc1.640028", "acodec": "none"},
            {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2"},
        ],
    }
    if mode == "music":
        info |= {"track": "晴天", "artist": "周杰倫"}
    if mode == "playlist":
        info = {"_type": "playlist", "id": "PL1", "title": "清單", "entries": []}
    if mode == "live":
        info |= {"is_live": True, "live_status": "is_live"}

    if "--dump-single-json" in args:
        _out(json.dumps(info, ensure_ascii=False))
        return 0

    folder = Path(_value(args, "--paths") or ".")
    stem = (_value(args, "--output") or "media.%(ext)s").split(".")[0]
    fields = {key: info[key] for key in ("title", "uploader") if key in info}
    _out("KFINFO " + json.dumps({"format_id": "137+140", **fields}, ensure_ascii=False))
    _out("KFSIZES [2000, 1000]")
    for part, size in (("137", 2000), ("140", 1000)):
        for done in (0, size // 2, size):
            status = "finished" if done == size else "downloading"
            _out(f'KFPROG "{part}" "{status}" {done} NA {size}')
            if mode == "slow":
                time.sleep(1.0)
    _out('KFPOST "started" "Merger"')
    _out('KFPOST "finished" "Merger"')
    source = os.environ.get("FAKE_YTDLP_MEDIA")
    target = folder / f"{stem}.wav"
    if source:
        shutil.copyfile(source, target)
    else:
        target.write_bytes(b"RIFF")
    (folder / f"{stem}.f137.mp4.part").write_bytes(b"left over")
    return 0


if __name__ == "__main__":
    sys.exit(main())
