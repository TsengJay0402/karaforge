from __future__ import annotations

import struct
import zlib
from itertools import pairwise
from pathlib import Path

import pytest

from karaforge.io.exporters.png import write_bottom_gradient, write_rgba_png

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def parse_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data.startswith(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    offset = len(PNG_SIGNATURE)
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        (crc,) = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])
        assert crc == zlib.crc32(kind + payload) & 0xFFFFFFFF
        chunks.append((kind, payload))
        offset += 12 + length
    return chunks


def decode_pixels(data: bytes, width: int, height: int) -> list[bytes]:
    chunks = dict(parse_chunks(data))
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = width * 4 + 1
    assert len(raw) == stride * height
    rows: list[bytes] = []
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        assert row[0] == 0  # filter type None
        rows.append(row[1:])
    return rows


def test_write_rgba_png_header(tmp_path: Path) -> None:
    path = tmp_path / "out.png"
    rows = [bytes((i, 0, 0, 255)) * 3 for i in range(2)]
    write_rgba_png(path, 3, 2, rows)
    data = path.read_bytes()
    assert data.startswith(PNG_SIGNATURE)
    chunks = parse_chunks(data)
    assert chunks[0][0] == b"IHDR"
    width, height, depth, color_type = struct.unpack(">IIBB", chunks[0][1][:10])
    assert width == 3
    assert height == 2
    assert depth == 8
    assert color_type == 6
    assert [kind for kind, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]


def test_write_rgba_png_pixel_data_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "out.png"
    rows = [bytes((y * 10, 20, 30, 255)) * 4 for y in range(3)]
    write_rgba_png(path, 4, 3, rows)
    decoded = decode_pixels(path.read_bytes(), 4, 3)
    assert decoded == rows


def test_write_rgba_png_row_count_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "out.png"
    rows = [bytes(4 * 4)] * 3
    with pytest.raises(ValueError):
        write_rgba_png(path, 4, 2, rows)


def test_write_rgba_png_row_length_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "out.png"
    rows = [bytes(4 * 4), bytes(4 * 4 + 1)]
    with pytest.raises(ValueError):
        write_rgba_png(path, 4, 2, rows)


def test_write_bottom_gradient_alpha_values(tmp_path: Path) -> None:
    path = tmp_path / "gradient.png"
    width, height, strength = 8, 400, 1.0
    write_bottom_gradient(path, width, height, strength)
    rows = decode_pixels(path.read_bytes(), width, height)
    assert rows[0][3] == 0  # top row fully transparent
    # Height 400 puts the eased gradient close enough to full strength at the bottom.
    assert rows[-1][3] == pytest.approx(round(255 * strength), abs=3)
    alphas = [row[3] for row in rows]
    assert all(later >= earlier for earlier, later in pairwise(alphas))
    for row in rows:
        assert set(row[: width * 4 : 4]) == {0}  # red
        assert set(row[1 : width * 4 : 4]) == {0}  # green
        assert set(row[2 : width * 4 : 4]) == {0}  # blue


def test_write_bottom_gradient_zero_strength_is_transparent(tmp_path: Path) -> None:
    path = tmp_path / "gradient.png"
    write_bottom_gradient(path, 4, 20, 0.0)
    rows = decode_pixels(path.read_bytes(), 4, 20)
    for row in rows:
        assert set(row[3::4]) == {0}
