import numpy as np
import numpy.typing as npt

_F64 = npt.NDArray[np.float64]

__version__: str

def dio(
    x: _F64,
    fs: int,
    f0_floor: float = 71.0,
    f0_ceil: float = 800.0,
    channels_in_octave: float = 2.0,
    frame_period: float = 5.0,
    speed: int = 1,
    allowed_range: float = 0.1,
) -> tuple[_F64, _F64]: ...
def harvest(
    x: _F64, fs: int, f0_floor: float = 71.0, f0_ceil: float = 800.0, frame_period: float = 5.0
) -> tuple[_F64, _F64]: ...
def stonemask(x: _F64, f0: _F64, temporal_positions: _F64, fs: int) -> _F64: ...
def cheaptrick(
    x: _F64,
    f0: _F64,
    temporal_positions: _F64,
    fs: int,
    q1: float = -0.15,
    f0_floor: float = 71.0,
    fft_size: int | None = None,
) -> _F64: ...
def d4c(
    x: _F64,
    f0: _F64,
    temporal_positions: _F64,
    fs: int,
    threshold: float = 0.85,
    fft_size: int | None = None,
) -> _F64: ...
def synthesize(
    f0: _F64, spectrogram: _F64, aperiodicity: _F64, fs: int, frame_period: float = 5.0
) -> _F64: ...
