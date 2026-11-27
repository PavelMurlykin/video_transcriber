import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from local_transcriber.cli import main
from local_transcriber.config import ASR_PATH_FIELDS, ConfigurationError
from local_transcriber.core import pipeline
from local_transcriber.core.transcription import ASREngine, ASROptions, read_terms
from local_transcriber.domain.errors import ASROutOfMemory


@pytest.fixture
def model_stubs(tmp_path, monkeypatch):
    calls = {}

    class TorchOOM(RuntimeError):
        pass

    def load_vad(device, **options):
        calls["vad"] = {"device": device, **options}
        return object()

    def transcribe(audio, **options):
        calls["transcribe"] = options
        if "error" in calls:
            raise calls["error"]
        return {"language": options["language"] or "ru", "segments": []}

    def load_model(path, **options):
        calls["model"] = {"path": path, **options}
        return SimpleNamespace(transcribe=transcribe)

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        device=lambda device: device, cuda=SimpleNamespace(OutOfMemoryError=TorchOOM),
    ))
    monkeypatch.setitem(sys.modules, "whisperx", SimpleNamespace(load_model=load_model))
    monkeypatch.setitem(sys.modules, "whisperx.vads.pyannote", SimpleNamespace(Pyannote=load_vad))
    vad = tmp_path / "vad.bin"
    vad.touch()
    return ASREngine(tmp_path, vad, "cuda", "float16"), calls, TorchOOM


@pytest.mark.parametrize(("mode", "expected"), [("ru", "ru"), ("auto", None), ("en", "en")])
def test_whisperx_uses_local_assets_language_vad_and_terms(model_stubs, mode, expected):
    engine, calls, _ = model_stubs
    result = engine.transcribe(object(), language=mode, batch_size=4, terms="SDK, Example")
    assert calls["model"]["path"] == str(engine.model_dir)
    assert calls["vad"]["model_fp"] == str(engine.vad_path)
    assert calls["model"]["local_files_only"] is True
    assert calls["model"]["asr_options"] == {"beam_size": 5, "hotwords": "SDK, Example"}
    assert calls["model"]["language"] == calls["transcribe"]["language"] == expected
    assert calls["transcribe"]["task"] == "transcribe"
    assert calls["transcribe"]["batch_size"] == 4
    assert result["language"] == (expected or "ru")


@pytest.mark.parametrize("kind", ["torch", "ctranslate2"])
def test_cuda_memory_errors_are_classified(model_stubs, kind):
    engine, calls, torch_oom = model_stubs
    calls["error"] = (torch_oom("allocation failed") if kind == "torch"
                      else RuntimeError("CUDA failed with error out of memory"))
    with pytest.raises(ASROutOfMemory):
        engine.transcribe(object(), language="ru", batch_size=4)


def test_other_runtime_errors_keep_original_type(model_stubs):
    engine, calls, _ = model_stubs
    calls["error"] = RuntimeError("synthetic incompatible driver")
    with pytest.raises(RuntimeError) as error:
        engine.transcribe(object(), language="ru", batch_size=4)
    assert error.value is calls["error"]


def test_terms_file_requires_utf8_and_limits_size(tmp_path):
    path = tmp_path / "Подсказки теста.txt"
    path.write_text("  SDK  \n\nТермин\n", encoding="utf-8-sig")
    assert read_terms(path) == "SDK, Термин"
    path.write_bytes(b"\xff")
    with pytest.raises(ConfigurationError, match="UTF-8"):
        read_terms(path)
    path.write_bytes(b"x" * 4097)
    with pytest.raises(ConfigurationError, match="4096"):
        read_terms(path)


def test_memory_profile_does_not_raise_a_smaller_configured_batch():
    options = ASROptions(profile="memory")
    assert options.inference_settings({"device": "cuda", "batch_size": 4}) == ("int8_float16", 2)
    assert options.inference_settings({"device": "cuda", "batch_size": 1}) == ("int8_float16", 1)


@pytest.fixture
def pipeline_inputs(tmp_path, monkeypatch):
    config = {key: str(tmp_path / key) for key in ASR_PATH_FIELDS}
    Path(config["manifest"]).write_text("{}", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    source = tmp_path / "input.wav"
    run_dir = tmp_path / "run"

    def verify(config, _directory, *, asr_only, **_kwargs):
        assert asr_only
        assert "alignment" not in config and "diarization" not in config
        return []

    def prepare(source, target, config):
        target.write_bytes(b"synthetic WAV placeholder")
        return {"duration_ms": 2000, "sample_rate": 16000, "channels": 1}

    monkeypatch.setattr(pipeline, "check_runtime", verify)
    monkeypatch.setattr(pipeline, "prepare_audio", prepare)
    return ["--config", str(config_path), "asr", str(source), "--run-dir", str(run_dir)], run_dir


def test_asr_updates_project_and_stops_before_alignment(pipeline_inputs, capsys, monkeypatch):
    args, run_dir = pipeline_inputs

    def run_inference(stage, job, config_path, options):
        assert stage == "asr" and options.language == "auto"
        checkpoint = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))
        assert checkpoint["completed_stages"] == ["audio"]
        raw = {"language": "en", "segments": [
            {"start": 0.1, "end": 2.01, "text": "Synthetic phrase"}
        ]}
        (run_dir / "asr.json").write_text(json.dumps(raw), encoding="utf-8")
        return {"stage": stage, "status": "completed", "exit_code": 0, "wall_seconds": 0.01}

    monkeypatch.setattr(pipeline, "_run_inference", run_inference)
    assert main([*args, "--language", "auto"]) == 0
    result = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))
    assert result["completed_stages"] == ["audio", "asr"]
    assert result["language"] == "en"
    assert result["segments"][0]["end_ms"] == 2000
    assert result["segments"][0]["speaker_id"] == "unknown"
    assert result["segments"][0]["words"] == []
    assert not (run_dir / "audio.wav").exists()
    assert "Synthetic phrase" not in capsys.readouterr().out


def test_cli_offers_one_memory_retry_and_keeps_checkpoint(pipeline_inputs, capsys, monkeypatch):
    args, run_dir = pipeline_inputs
    calls = []

    def run_inference(stage, job, config_path, options):
        calls.append(stage)
        return {"stage": stage, "status": "failed", "exit_code": 1,
                "error_code": ASROutOfMemory.code, "wall_seconds": 0.01}

    monkeypatch.setattr(pipeline, "_run_inference", run_inference)
    assert main(args) == 1
    error = json.loads(capsys.readouterr().err)
    assert error["error_code"] == ASROutOfMemory.code
    assert "--profile memory" in error["hint"]
    assert calls == ["asr"]
    result = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))
    assert result["completed_stages"] == ["audio"]
    assert (run_dir / "audio.wav").exists()
