"""Join several synthetic songs into one long song, with its lyrics and its known answer.

The synthetic songs are under a minute and a half each.  To see how KaraForge behaves on a
song of normal length, join a few of them::

    python scripts/join_songs.py tests/fixtures/songs/zh-2000 tests/fixtures/songs/zh-2000 \\
        --audio mix_snr10.mp3 -o long/
    kf auto long/song.wav long/lyrics.txt -o long/long-ktv.mp4
    python scripts/compare_with_truth.py long/long-ktv.kfproj long/truth.json

Every input folder holds an audio file and the ``truth.json`` written by the benchmark's
generator (``tests/fixtures/songs/zh-2000`` is one such folder, with ``mix_snr10.mp3``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


def join(folders: list[Path], audio_name: str, out_dir: Path) -> tuple[float, int, int]:
    """Write ``song.wav``, ``lyrics.txt`` and ``truth.json``; return seconds, lines, tokens."""
    pieces: list[Any] = []
    lyrics = ["# title: 長度測試（合成歌曲相接）", "# artist: KaraForge Synth", ""]
    lines: list[dict[str, Any]] = []
    rate = 0
    offset_ms = 0
    for folder in folders:
        audio, song_rate = sf.read(folder / audio_name, dtype="float32", always_2d=True)
        if rate and song_rate != rate:
            raise SystemExit(f"{folder}: sample rate {song_rate} differs from {rate}")
        rate = int(song_rate)
        pieces.append(audio)
        truth: dict[str, Any] = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
        for line in truth["lines"]:
            lyrics.append(str(line["text"]))
            lines.append(
                {
                    "text": line["text"],
                    "tokens": [
                        {
                            "text": token["text"],
                            "start_ms": int(token["start_ms"]) + offset_ms,
                            "end_ms": int(token["end_ms"]) + offset_ms,
                        }
                        for token in line["tokens"]
                    ],
                }
            )
        lyrics.append("")
        offset_ms += round(1000 * audio.shape[0] / rate)
    joined = np.concatenate(pieces)
    out_dir.mkdir(parents=True, exist_ok=True)
    sf.write(out_dir / "song.wav", joined, rate, subtype="PCM_16")
    (out_dir / "lyrics.txt").write_text("\n".join(lyrics) + "\n", encoding="utf-8")
    (out_dir / "truth.json").write_text(
        json.dumps({"song_id": "joined", "lines": lines}, ensure_ascii=False), encoding="utf-8"
    )
    return joined.shape[0] / rate, len(lines), sum(len(line["tokens"]) for line in lines)


def main() -> int:
    """Join the songs named on the command line."""
    parser = argparse.ArgumentParser(description="Join synthetic songs into one long song.")
    parser.add_argument("folders", nargs="+", type=Path, help="song folders, in order")
    parser.add_argument("--audio", default="mix_snr10.wav", help="audio file name in each folder")
    parser.add_argument("-o", "--out", type=Path, required=True, help="output folder")
    arguments = parser.parse_args()
    seconds, lines, tokens = join(arguments.folders, arguments.audio, arguments.out)
    print(f"{len(arguments.folders)} songs, {seconds:.1f} s, {lines} lines, {tokens} tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
