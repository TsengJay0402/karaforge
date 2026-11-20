"""A minimal PNG writer (no imaging library needed) for generated overlay images."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def write_rgba_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    """Write an 8-bit RGBA PNG.

    Args:
        path: Output file.
        width: Image width in pixels.
        height: Image height in pixels.
        rows: ``height`` byte strings of ``width * 4`` bytes each (R, G, B, A per pixel).
    """
    if len(rows) != height or any(len(row) != width * 4 for row in rows):
        raise ValueError("rows do not match the image size")
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def write_bottom_gradient(path: Path, width: int, height: int, strength: float) -> None:
    """Write a black overlay that is transparent at the top and darkest at the bottom edge.

    The gradient covers the lower 55 % of the frame, which is where the lyric rows sit, and
    eases in so that there is no visible edge.

    Args:
        path: Output file.
        width: Frame width.
        height: Frame height.
        strength: Opacity at the bottom edge, 0–1.
    """
    start = round(height * 0.45)
    rows: list[bytes] = []
    for y in range(height):
        position = max(0.0, (y - start) / max(1, height - start))
        alpha = round(255 * min(1.0, max(0.0, strength)) * position**1.6)
        rows.append(bytes((0, 0, 0, alpha)) * width)
    write_rgba_png(path, width, height, rows)
