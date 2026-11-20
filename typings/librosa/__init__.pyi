from typing import Any

import numpy as np
import numpy.typing as npt

from . import beat as beat
from . import onset as onset

__version__: str

def pyin(
    y: npt.NDArray[np.floating[Any]],
    *,
    fmin: float,
    fmax: float,
    sr: float = 22050,
    frame_length: int = 2048,
    hop_length: int | None = None,
    fill_na: float | None = ...,
    center: bool = True,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_], npt.NDArray[np.float64]]: ...
def hz_to_midi(frequencies: Any) -> Any: ...
