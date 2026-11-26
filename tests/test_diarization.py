import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from local_transcriber.config import ConfigurationError, PATH_FIELDS, load_config, speaker_count_options
from local_transcriber.core.diarization import DiarizationEngine


@pytest.mark.parametrize(("config", "expected"), [
    ({}, {"num_speakers": 2}),
    ({"num_speakers": None}, {}),
    ({"num_speakers": 3}, {"num_speakers": 3}),
    ({"min_speakers": 2, "max_speakers": 3}, {"min_speakers": 2, "max_speakers": 3}),
])
def test_config_selects_exact_auto_or_range(tmp_path, config, expected):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({**{key: str(tmp_path / key) for key in PATH_FIELDS}, **config}))
    assert speaker_count_options(load_config(path)) == expected


@pytest.mark.parametrize("config", [
    {"num_speakers": True},
    {"min_speakers": 2},
    {"min_speakers": 3, "max_speakers": 2},
    {"min_speakers": 0, "max_speakers": 2},
    {"num_speakers": 2, "min_speakers": 2, "max_speakers": 3},
])
def test_invalid_speaker_limits_are_rejected(config):
    with pytest.raises(ConfigurationError):
        speaker_count_options(config)


def test_engine_passes_range_to_local_pipeline_and_reads_both_tracks(tmp_path, monkeypatch):
    calls = {}

    def annotation(rows):
        def itertracks(*, yield_label):
            assert yield_label
            return [(SimpleNamespace(start=start, end=end), index, label)
                    for index, (start, end, label) in enumerate(rows)]
        return SimpleNamespace(itertracks=itertracks)

    class Pipeline:
        @classmethod
        def from_pretrained(cls, path):
            calls["path"] = path
            return cls()

        def to(self, device):
            calls["device"] = device

        def __call__(self, audio, **options):
            calls["audio"] = audio
            calls["options"] = options
            return SimpleNamespace(
                speaker_diarization=annotation([(0, 0.8, "A"), (0.5, 1, "B")]),
                exclusive_speaker_diarization=annotation([(0, 0.6, "A"), (0.6, 1, "B")]),
            )

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        device=lambda item: item, from_numpy=lambda _: SimpleNamespace(unsqueeze=lambda _: "mono"),
    ))
    monkeypatch.setitem(sys.modules, "pyannote.audio", SimpleNamespace(Pipeline=Pipeline))
    engine = DiarizationEngine(tmp_path, "cuda")
    result = engine.diarize(object(), {"min_speakers": 2, "max_speakers": 3})
    assert calls == {
        "path": str(tmp_path.resolve()), "device": "cuda",
        "audio": {"waveform": "mono", "sample_rate": 16000},
        "options": {"min_speakers": 2, "max_speakers": 3},
    }
    assert result["turns"][1] == {"start": 0.5, "end": 1.0, "speaker": "B"}
    assert result["exclusive_turns"][1] == {"start": 0.6, "end": 1.0, "speaker": "B"}


def test_engine_rejects_remote_model_id():
    with pytest.raises(ConfigurationError, match="absolute local path"):
        DiarizationEngine(Path("pyannote/speaker-diarization-community-1"), "cpu")
