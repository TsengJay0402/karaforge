from typing import Any

class Tokenizer:
    eot: int
    sot_sequence: list[int]
    def __init__(
        self, tokenizer: Any, multilingual: bool, task: str | None = None, language: str | None = None
    ) -> None: ...
    def encode(self, text: str) -> list[int]: ...
    def decode(self, tokens: list[int]) -> str: ...
