"""Local pyannote Community-1 adapter."""

from pathlib import Path

from local_transcriber.config import ConfigurationError

from .media import SAMPLE_RATE


def _turns(annotation) -> list[dict]:
    return [
        {"start": float(turn.start), "end": float(turn.end), "speaker": str(label)}
        for turn, _, label in annotation.itertracks(yield_label=True)
    ]


class DiarizationEngine:
    def __init__(self, model_dir: Path, device: str):
        if not model_dir.is_absolute() or str(model_dir).startswith(("\\\\", "//")):
            raise ConfigurationError("Community-1 needs an absolute local path")
        if not model_dir.is_dir():
            raise ConfigurationError("Community-1 model directory is missing")
        model_dir = model_dir.resolve()
        if str(model_dir).startswith(("\\\\", "//")):
            raise ConfigurationError("Community-1 needs an absolute local path")
        self.model_dir = model_dir
        self.device = device

    def diarize(self, audio, speaker_options: dict[str, int]) -> dict:
        import torch
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(str(self.model_dir))
        if pipeline is None:
            raise RuntimeError("LOCAL_DIARIZATION_MODEL_UNAVAILABLE")
        try:
            pipeline.to(torch.device(self.device))
            output = pipeline(
                {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": SAMPLE_RATE},
                **speaker_options,
            )
            return {
                "turns": _turns(output.speaker_diarization),
                "exclusive_turns": _turns(output.exclusive_speaker_diarization),
            }
        finally:
            del pipeline
