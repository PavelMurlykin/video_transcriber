"""WhisperX adapter for offline, multilingual speech recognition with local VAD."""

from dataclasses import dataclass
from pathlib import Path

from local_transcriber.config import ConfigurationError
from local_transcriber.domain.errors import ASROutOfMemory

BEAM_SIZE = 5
LANGUAGES = ("ru", "auto", "en")
PROFILES = ("default", "memory")
MAX_TERMS_BYTES = 4096


@dataclass(frozen=True)
class ASROptions:
    language: str = "ru"
    profile: str = "default"
    terms_file: Path | None = None

    def inference_settings(self, config: dict) -> tuple[str, int]:
        if self.profile == "memory":
            compute_type = "int8_float16" if config["device"] == "cuda" else "int8"
            return compute_type, min(2, config["batch_size"])
        return config["compute_type"], config["batch_size"]


def read_terms(path: Path | None) -> str | None:
    if path is None:
        return None
    path_error = "terms-file must be a readable local UTF-8 text file"
    if str(path).startswith(("\\\\", "//")):
        raise ConfigurationError(path_error)
    try:
        resolved = path.resolve(strict=True)
        if str(resolved).startswith(("\\\\", "//")) or not resolved.is_file():
            raise ConfigurationError(path_error)
        with resolved.open("rb") as stream:
            data = stream.read(MAX_TERMS_BYTES + 1)
        if len(data) > MAX_TERMS_BYTES:
            raise ConfigurationError("terms-file must be at most 4096 bytes")
        terms = [line.strip() for line in data.decode("utf-8-sig").splitlines() if line.strip()]
    except (OSError, UnicodeError):
        raise ConfigurationError(path_error) from None
    return ", ".join(terms) or None


def _cuda_out_of_memory(error: RuntimeError, torch) -> bool:
    message = str(error).lower()
    return isinstance(error, torch.cuda.OutOfMemoryError) or any(
        marker in message for marker in (
            "cuda out of memory", "cuda error: out of memory", "cuda failed with error out of memory",
            "cuda_error_out_of_memory", "cublas_status_alloc_failed", "cudnn_status_alloc_failed",
        )
    )


class ASREngine:
    """Load local Large V3 and local VAD for one ASR stage."""

    def __init__(self, model_dir: Path, vad_path: Path, device: str, compute_type: str):
        for path in (model_dir, vad_path):
            if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
                raise ConfigurationError("ASR and VAD need absolute local paths")
        if not model_dir.is_dir() or not vad_path.is_file():
            raise ConfigurationError("ASR model directory or VAD weights are missing")
        self.model_dir = model_dir
        self.vad_path = vad_path
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio, *, language: str, batch_size: int, terms: str | None = None) -> dict:
        import torch
        import whisperx
        from whisperx.vads.pyannote import Pyannote

        model_language = None if language == "auto" else language
        vad_options = {"vad_onset": 0.5, "vad_offset": 0.363}
        vad = engine = None
        try:
            vad = Pyannote(torch.device(self.device), model_fp=str(self.vad_path), **vad_options)
            engine = whisperx.load_model(
                str(self.model_dir), device=self.device, compute_type=self.compute_type,
                language=model_language, local_files_only=True, vad_model=vad,
                vad_options=vad_options, asr_options={"beam_size": BEAM_SIZE, "hotwords": terms},
                threads=4,
            )
            return engine.transcribe(
                audio, batch_size=batch_size, language=model_language, task="transcribe",
                print_progress=False, verbose=False,
            )
        except RuntimeError as error:
            if self.device == "cuda" and _cuda_out_of_memory(error, torch):
                raise ASROutOfMemory from None
            raise
        finally:
            del engine, vad
