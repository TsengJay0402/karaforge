"""Editing operations on a project document that need the engine's text rules."""

from __future__ import annotations

from difflib import SequenceMatcher

from karaforge.io.importers.lyrics_txt import tokens_from_text
from karaforge.project.schema import Line, Token
from karaforge.text.tokenize import core_of

EDITED_CONFIDENCE = 0.2
"""Confidence of tokens whose time was estimated after an edit."""
_MIN_SLOT_MS = 60


def _key(token: Token) -> str:
    """What makes two tokens "the same" across an edit: the sung text, case-insensitively."""
    return core_of(token.text).casefold() or token.text.strip()


def _spread(tokens: list[Token], start_ms: int, end_ms: int) -> list[Token]:
    """Give ``tokens`` equal shares of ``[start_ms, end_ms]`` as estimated, unlocked times."""
    share = (end_ms - start_ms) / len(tokens)
    spread: list[Token] = []
    for index, token in enumerate(tokens):
        begin = round(start_ms + index * share)
        finish = round(start_ms + (index + 1) * share) if index < len(tokens) - 1 else end_ms
        spread.append(
            token.model_copy(
                update={
                    "start_ms": begin,
                    "end_ms": max(begin, finish),
                    "confidence": EDITED_CONFIDENCE,
                    "locked": False,
                    "source": "auto",
                }
            )
        )
    return spread


def retokenize_line(line: Line, text: str) -> Line:
    """Replace the text of a line, keeping the timing of everything that is still there.

    The old and the new token sequences are compared with a diff:

    * tokens that survive keep their times, lock state, confidence and reading;
    * a token whose text was *corrected* (one token replaced by one token) keeps its time —
      fixing a wrong character does not move it in the song — but loses its reading, which
      belonged to the old character;
    * a stretch that was replaced by a different number of tokens shares the old stretch's
      time evenly, as an estimate (low confidence, not locked);
    * inserted tokens are fitted into the pause between their neighbours when there is one,
      and are left without a time otherwise (the layout draws them, the next alignment
      places them).

    Args:
        line: The line as it is.
        text: Its new text, in the lyrics-file syntax (``字{reading}`` sets a reading).

    Returns:
        A new line with the same id, singer, paragraph and time hint.
    """
    old = list(line.tokens)
    new = tokens_from_text(text)
    matcher = SequenceMatcher(
        a=[_key(token) for token in old], b=[_key(token) for token in new], autojunk=False
    )
    result: list[Token] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        before, after = old[old_start:old_end], new[new_start:new_end]
        if tag == "equal":
            for kept, fresh in zip(before, after, strict=True):
                update: dict[str, object] = {"text": fresh.text}
                if fresh.ruby is not None:
                    update |= {"ruby": fresh.ruby, "ruby_source": "manual"}
                result.append(kept.model_copy(update=update))
        elif tag == "replace" and len(before) == len(after):
            for kept, fresh in zip(before, after, strict=True):
                result.append(
                    kept.model_copy(
                        update={
                            "text": fresh.text,
                            "ruby": fresh.ruby,
                            "ruby_source": fresh.ruby_source,
                        }
                    )
                )
        elif tag == "replace":
            timed = [token for token in before if token.start_ms is not None]
            if timed and timed[0].start_ms is not None and timed[-1].end_ms is not None:
                result.extend(_spread(after, timed[0].start_ms, timed[-1].end_ms))
            else:
                result.extend(after)
        elif tag == "insert":
            previous_end = next(
                (token.end_ms for token in reversed(result) if token.end_ms is not None), None
            )
            following_start = next(
                (token.start_ms for token in old[old_end:] if token.start_ms is not None), None
            )
            if (
                previous_end is not None
                and following_start is not None
                and following_start - previous_end >= _MIN_SLOT_MS * len(after)
            ):
                result.extend(_spread(after, previous_end, following_start))
            else:
                result.extend(after)
        # "delete": the tokens are simply gone.
    return line.model_copy(update={"tokens": result})
