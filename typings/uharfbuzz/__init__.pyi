from collections.abc import Sequence

__version__: str

class Blob:
    def __init__(self, data: bytes = ...) -> None: ...
    @classmethod
    def from_file_path(cls, path: str) -> Blob: ...

class Face:
    upem: int
    def __init__(self, blob: Blob | bytes = ..., index: int = 0) -> None: ...

class Font:
    scale: tuple[int, int]
    def __init__(self, face: Face = ...) -> None: ...
    def get_nominal_glyph(self, unicode: int) -> int | None: ...

class GlyphInfo:
    codepoint: int
    cluster: int

class GlyphPosition:
    x_advance: int
    y_advance: int
    x_offset: int
    y_offset: int

class Buffer:
    glyph_infos: Sequence[GlyphInfo]
    glyph_positions: Sequence[GlyphPosition]
    direction: str
    def __init__(self) -> None: ...
    def add_str(self, text: str, item_offset: int = 0, item_length: int = -1) -> None: ...
    def guess_segment_properties(self) -> None: ...

def shape(font: Font, buffer: Buffer, features: dict[str, bool | int] | None = None) -> None: ...
