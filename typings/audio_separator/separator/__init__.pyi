from typing import Any

class Separator:
    output_dir: str
    model_instance: Any
    def __init__(
        self,
        log_level: int = ...,
        log_formatter: Any = None,
        model_file_dir: str = ...,
        output_dir: str | None = None,
        output_format: str = "WAV",
        output_bitrate: str | None = None,
        normalization_threshold: float = 0.9,
        amplification_threshold: float = 0.0,
        output_single_stem: str | None = None,
        invert_using_spec: bool = False,
        sample_rate: int = 44100,
        use_soundfile: bool = False,
        use_autocast: bool = False,
        use_directml: bool = False,
        chunk_duration: float | None = None,
        mdx_params: dict[str, Any] = ...,
        vr_params: dict[str, Any] = ...,
        demucs_params: dict[str, Any] = ...,
        mdxc_params: dict[str, Any] = ...,
    ) -> None: ...
    def load_model(self, model_filename: str = ..., force_reload: bool = False) -> None: ...
    def separate(
        self, audio_file_path: str | list[str], custom_output_names: dict[str, str] | None = None
    ) -> list[str]: ...
