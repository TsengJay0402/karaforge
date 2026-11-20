from typing import Any

import numpy as np
import numpy.typing as npt

def beat_track(
    *,
    y: npt.NDArray[np.floating[Any]] | None = None,
    sr: float = 22050,
    onset_envelope: npt.NDArray[np.floating[Any]] | None = None,
    hop_length: int = 512,
    start_bpm: float = 120.0,
    tightness: float = 100,
    trim: bool = True,
    units: str = "frames",
) -> tuple[Any, npt.NDArray[Any]]: ...
