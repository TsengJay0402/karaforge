from os import PathLike
from types import TracebackType
from typing import Any, BinaryIO, Literal

import numpy as np
import numpy.typing as npt

_Path = str | PathLike[str]
_DType = Literal["float32", "float64", "int16", "int32"]

class _Info:
    samplerate: int
    channels: int
    frames: int
    duration: float
    format: str
    subtype: str

class SoundFile:
    samplerate: int
    channels: int
    frames: int
    def __init__(
        self,
        file: _Path,
        mode: str = "r",
        samplerate: int | None = None,
        channels: int | None = None,
        subtype: str | None = None,
        format: str | None = None,
    ) -> None: ...
    def __enter__(self) -> SoundFile: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    def read(
        self, frames: int = -1, dtype: _DType = "float64", always_2d: bool = False
    ) -> npt.NDArray[Any]: ...
    def write(self, data: npt.NDArray[Any]) -> None: ...
    def seek(self, frames: int, whence: int = 0) -> int: ...
    def tell(self) -> int: ...
    def close(self) -> None: ...

def read(
    file: _Path,
    frames: int = -1,
    start: int = 0,
    stop: int | None = None,
    dtype: _DType = "float64",
    always_2d: bool = False,
) -> tuple[npt.NDArray[Any], int]: ...
def write(
    file: _Path | BinaryIO,
    data: npt.NDArray[np.floating[Any]] | npt.NDArray[np.integer[Any]],
    samplerate: int,
    subtype: str | None = None,
    format: str | None = None,
) -> None: ...
def info(file: _Path) -> _Info: ...
