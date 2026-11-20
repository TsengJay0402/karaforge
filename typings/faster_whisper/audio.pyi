import numpy as np
import numpy.typing as npt

def pad_or_trim(
    array: npt.NDArray[np.float32], length: int = 3000, *, axis: int = -1
) -> npt.NDArray[np.float32]: ...
