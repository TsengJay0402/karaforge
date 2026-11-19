"""Exception hierarchy shared by the engine, the CLI and the server.

Every error carries two audiences' worth of information:

* a short message for the *user*, in Traditional Chinese and English, optionally with a hint
  about what to do next;
* a ``detail`` string for the *developer* (command lines, tracebacks, raw tool output).

The CLI prints the user message (plus the detail with ``--verbose``); the server serialises
:meth:`KaraForgeError.to_dict` into the HTTP response and job events.
"""

from __future__ import annotations

from typing import Literal

Lang = Literal["zh", "en"]


class KaraForgeError(Exception):
    """Base class for every error that KaraForge raises on purpose.

    Attributes:
        code: Stable machine-readable identifier (also the default HTTP error code).
        message_zh: User-facing message in Traditional Chinese.
        message_en: User-facing message in English.
        hint_zh: Optional suggestion for the user, Traditional Chinese.
        hint_en: Optional suggestion for the user, English.
        detail: Optional developer-facing detail.
    """

    code: str = "internal_error"

    def __init__(
        self,
        message_zh: str,
        message_en: str,
        *,
        hint_zh: str | None = None,
        hint_en: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message_en)
        self.message_zh = message_zh
        self.message_en = message_en
        self.hint_zh = hint_zh
        self.hint_en = hint_en
        self.detail = detail

    def user_message(self, lang: Lang = "zh") -> str:
        """Return the message (and hint, when present) in the requested language."""
        message = self.message_zh if lang == "zh" else self.message_en
        hint = self.hint_zh if lang == "zh" else self.hint_en
        return f"{message}\n{hint}" if hint else message

    def to_dict(self) -> dict[str, str | None]:
        """Serialise the error for API responses and job events."""
        return {
            "code": self.code,
            "message_zh": self.message_zh,
            "message_en": self.message_en,
            "hint_zh": self.hint_zh,
            "hint_en": self.hint_en,
            "detail": self.detail,
        }

    def __str__(self) -> str:
        if self.detail:
            return f"{self.message_en} ({self.detail})"
        return self.message_en


class ToolMissingError(KaraForgeError):
    """An external program (ffmpeg, ffprobe, …) is missing or lacks a required feature."""

    code = "tool_missing"


class MediaError(KaraForgeError):
    """The input media cannot be read, decoded or is of an unsupported kind."""

    code = "media_error"


class LyricsFormatError(KaraForgeError):
    """A lyrics or subtitle file could not be parsed."""

    code = "lyrics_format_error"


class ProjectError(KaraForgeError):
    """A ``.kfproj`` folder is missing, corrupt or of an unsupported schema version."""

    code = "project_error"


class RevisionConflictError(ProjectError):
    """The project was modified by someone else since it was loaded."""

    code = "revision_conflict"


class ModelError(KaraForgeError):
    """Model weights are missing, corrupt or could not be loaded."""

    code = "model_error"


class DependencyMissingError(KaraForgeError):
    """An optional Python dependency needed by the selected adapter is not installed."""

    code = "dependency_missing"


class PipelineError(KaraForgeError):
    """A pipeline stage failed or the pipeline was configured inconsistently."""

    code = "pipeline_error"


class AlignmentError(PipelineError):
    """Lyrics could not be aligned to the audio."""

    code = "alignment_error"


class ExportError(KaraForgeError):
    """Rendering or writing an output file failed."""

    code = "export_error"


class ThemeError(KaraForgeError):
    """A theme file is missing or invalid."""

    code = "theme_error"


class JobCancelledError(KaraForgeError):
    """The running job was cancelled by the user."""

    code = "cancelled"

    def __init__(self) -> None:
        super().__init__("工作已取消。", "The job was cancelled.")
