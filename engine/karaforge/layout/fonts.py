"""Font discovery and text measurement.

Widths are measured with HarfBuzz (through ``uharfbuzz``), the same shaper libass uses, so
the glyph positions the layout engine computes are the positions libass will draw at.

One libass rule matters for everything here: an ASS font size is **not** the em size.  libass
(like GDI) scales a font so that ``usWinAscent + usWinDescent`` equals the font size.  A CJK
ideograph, which is one em wide, therefore comes out at
``font_size * unitsPerEm / (usWinAscent + usWinDescent)`` pixels — 89 % of the nominal size in
one font and 69 % in another.  Themes specify the em size (the height of a Chinese character)
and :meth:`FontFace.ass_size` converts it for each font.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uharfbuzz as hb
from fontTools.ttLib import TTFont, TTLibError

from karaforge import paths
from karaforge.errors import ThemeError

FONT_EXTENSIONS = (".ttf", ".otf")
_NAME_IDS = {"family": 1, "subfamily": 2, "full": 4, "postscript": 6, "license": 13}
_ENGLISH_US = 0x409


@dataclass(frozen=True)
class FontFace:
    """Metadata and vertical metrics of one font file."""

    path: Path
    family: str
    subfamily: str
    full_name: str
    postscript_name: str
    aliases: tuple[str, ...]
    """Every family, full and PostScript name in any language, lower-cased, for lookup."""
    units_per_em: int
    line_units: int
    """``usWinAscent + usWinDescent`` (with libass' fallbacks): what an ASS font size spans."""
    ascent_units: int
    """Distance from the top of the line box to the baseline, in font units."""
    ideograph_top_units: int
    """Top of the ideographic em box above the baseline (``sTypoAscender``)."""
    ideograph_bottom_units: int
    """Bottom of the ideographic em box below the baseline (positive)."""
    weight: int
    license: str

    def ass_size(self, em_px: float) -> float:
        """ASS ``Fontsize`` that renders this font with an em of ``em_px`` pixels."""
        return em_px * self.line_units / self.units_per_em

    def em_px(self, ass_size: float) -> float:
        """Em size in pixels when the font is used at ASS size ``ass_size``."""
        return ass_size * self.units_per_em / self.line_units


def _best_name(table: Any, name_id: int) -> str:
    """Prefer the English (US) Windows name, then anything decodable."""
    records: list[Any] = [record for record in table.names if record.nameID == name_id]
    for record in records:
        if record.platformID == 3 and record.langID == _ENGLISH_US:
            return str(record.toUnicode())
    for record in records:
        try:
            return str(record.toUnicode())
        except UnicodeDecodeError:
            continue
    return ""


def read_font(path: Path) -> FontFace:
    """Read names and metrics from a ``.ttf`` / ``.otf`` file.

    Raises:
        ThemeError: If the file is not a usable font.
    """
    try:
        with TTFont(path, lazy=True) as font:
            names = font["name"]
            head = font["head"]
            os2: Any = font["OS/2"] if "OS/2" in font else None  # noqa: SIM401
            hhea = font["hhea"]
            aliases: set[str] = set()
            for record in names.names:
                if record.nameID in (1, 4, 6, 16):
                    try:
                        aliases.add(str(record.toUnicode()).strip().lower())
                    except UnicodeDecodeError:
                        continue
            upm = int(head.unitsPerEm)
            win_ascent = int(os2.usWinAscent) if os2 is not None else 0
            win_descent = int(os2.usWinDescent) if os2 is not None else 0
            typo_ascent = int(os2.sTypoAscender) if os2 is not None else 0
            typo_descent = int(os2.sTypoDescender) if os2 is not None else 0
            # libass mimics GDI: Win metrics first, then typo metrics, then hhea.
            if win_ascent + win_descent > 0:
                ascent, line = win_ascent, win_ascent + win_descent
            elif typo_ascent - typo_descent != 0:
                ascent, line = typo_ascent, typo_ascent - typo_descent
            else:
                ascent, line = int(hhea.ascent), int(hhea.ascent) - int(hhea.descent)
            if typo_ascent - typo_descent == 0:
                typo_ascent, typo_descent = int(hhea.ascent), int(hhea.descent)
            return FontFace(
                path=path,
                family=_best_name(names, _NAME_IDS["family"]),
                subfamily=_best_name(names, _NAME_IDS["subfamily"]),
                full_name=_best_name(names, _NAME_IDS["full"]),
                postscript_name=_best_name(names, _NAME_IDS["postscript"]),
                aliases=tuple(sorted(alias for alias in aliases if alias)),
                units_per_em=upm,
                line_units=line,
                ascent_units=ascent,
                ideograph_top_units=typo_ascent,
                ideograph_bottom_units=-typo_descent,
                weight=int(os2.usWeightClass) if os2 is not None else 400,
                license=_best_name(names, _NAME_IDS["license"]),
            )
    except (TTLibError, OSError, KeyError, AttributeError) as exc:
        raise ThemeError(
            f"無法讀取字型檔：{path.name}",
            f"Cannot read font file: {path.name}",
            hint_zh="支援 .ttf 與 .otf（不支援 .ttc 字型集合，請先拆成單一字型）。",
            hint_en="Use .ttf or .otf files (.ttc collections are not supported).",
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


class Measurer:
    """Measures text in one font with HarfBuzz.  Results are in font units."""

    def __init__(self, face: FontFace) -> None:
        self.face = face
        blob = hb.Blob.from_file_path(str(face.path))
        self._font = hb.Font(hb.Face(blob))
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, bool], tuple[float, ...]] = {}

    def has_glyph(self, char: str) -> bool:
        """Whether the font has a glyph for ``char``."""
        return bool(self._font.get_nominal_glyph(ord(char)))

    def advances(self, text: str, *, kerned: bool = True) -> tuple[float, ...]:
        """Horizontal advance of every character of ``text``.

        The text is shaped as one run.  ``kerned`` mirrors what libass does: with
        ``Kerning: yes`` in the script (which KaraForge always writes) text *without* extra
        letter spacing gets pair kerning and ligatures, while any non-zero letter spacing
        switches both off.  A cluster of several characters — a ligature, or a base letter
        with combining marks — reports its whole advance on its first character and zero on
        the rest.

        Args:
            text: The run to shape.
            kerned: Apply pair kerning and ligatures (use ``False`` for letter-spaced text).
        """
        if not text:
            return ()
        key = (text, kerned)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            buffer = hb.Buffer()
            buffer.add_str(text)
            buffer.guess_segment_properties()
            hb.shape(self._font, buffer, {"kern": kerned, "liga": kerned, "clig": kerned})
            widths = [0.0] * len(text)
            for info, position in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
                widths[min(info.cluster, len(text) - 1)] += float(position.x_advance)
            result = tuple(widths)
            if len(self._cache) < 4096:
                self._cache[key] = result
            return result

    def width(self, text: str, *, kerned: bool = True) -> float:
        """Total advance of ``text`` in font units."""
        return sum(self.advances(text, kerned=kerned))


class FontLibrary:
    """The fonts KaraForge can use: the bundled ones plus the user's own.

    Args:
        directories: Folders to scan (non-recursively).  Defaults to the bundled fonts and
            ``$KARAFORGE_HOME/fonts``.
    """

    def __init__(self, directories: Sequence[Path] | None = None) -> None:
        self.directories = (
            list(directories)
            if directories is not None
            else [paths.bundled_dir("fonts"), paths.home_dir() / "fonts"]
        )
        self._faces: list[FontFace] | None = None
        self._measurers: dict[Path, Measurer] = {}
        self._lock = threading.Lock()

    @property
    def faces(self) -> list[FontFace]:
        """All readable fonts, bundled ones first."""
        with self._lock:
            if self._faces is None:
                found: list[FontFace] = []
                for directory in self.directories:
                    if not directory.is_dir():
                        continue
                    for path in sorted(directory.iterdir()):
                        if path.suffix.lower() in FONT_EXTENSIONS and path.is_file():
                            try:
                                found.append(read_font(path))
                            except ThemeError:
                                continue
                self._faces = found
            return list(self._faces)

    def find(self, name: str) -> FontFace:
        """Look up a font by family, full or PostScript name (any language, any case).

        Raises:
            ThemeError: If no such font is available.
        """
        wanted = name.strip().lower()
        for face in self.faces:
            if wanted in face.aliases or wanted == face.path.stem.lower():
                return face
        available = "、".join(face.family for face in self.faces) or "(無)"
        raise ThemeError(
            f"找不到字型「{name}」。",
            f"Font not found: {name}",
            hint_zh=f"可用的字型：{available}。自備字型請放到 {paths.home_dir() / 'fonts'}。",
            hint_en=f"Available fonts: {', '.join(face.family for face in self.faces) or 'none'}. "
            f"Put your own fonts into {paths.home_dir() / 'fonts'}.",
        )

    def measurer(self, face: FontFace) -> Measurer:
        """Return the (cached) measurer of ``face``."""
        with self._lock:
            if face.path not in self._measurers:
                self._measurers[face.path] = Measurer(face)
            return self._measurers[face.path]


_default_library: FontLibrary | None = None
_default_lock = threading.Lock()


def default_library() -> FontLibrary:
    """The shared library over the default font folders."""
    global _default_library
    with _default_lock:
        if _default_library is None:
            _default_library = FontLibrary()
        return _default_library
