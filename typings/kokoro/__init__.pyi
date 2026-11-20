from collections.abc import Iterator
from typing import Any

class _Result:
    graphemes: str
    phonemes: str
    audio: Any  # torch.FloatTensor | None

class KPipeline:
    def __init__(
        self,
        lang_code: str,
        repo_id: str | None = None,
        model: Any = True,
        trf: bool = False,
        device: str | None = None,
    ) -> None: ...
    def __call__(
        self,
        text: str | list[str],
        voice: str | None = None,
        speed: float = 1.0,
        split_pattern: str | None = r"\n+",
    ) -> Iterator[_Result]: ...
