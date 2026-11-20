from typing import Any

import numpy as np
import numpy.typing as npt

def onset_strength(
    *,
    y: npt.NDArray[np.floating[Any]] | None = None,
    sr: float = 22050,
    hop_length: int = 512,
) -> npt.NDArray[np.float32]: ...
