import json
from pathlib import Path

import pytest

from local_transcriber.cli import main
from local_transcriber.config import ConfigurationError, load_config
from local_transcriber.core import runtime
from local_transcriber.domain.errors import MediaError

from test_models import model_fixture


def test_runtime_diagnostics_filter_model_filenames(tmp_path, monkeypatch, capsys):
    config = model_fixture(tmp_path)
    manifest = Path(config["manifest"])
    inventory = json.loads(manifest.read_text(encoding="utf-8"))
    inventory["models"]["asr"]["files"][0]["path"] = "synthetic-private-filename.wav"
    manifest.write_text(json.dumps(inventory), encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(runtime, "_check_media_tools", lambda _: ["MEDIA_TOOL_UNAVAILABLE:ffmpeg"])
    monkeypatch.setattr(runtime, "_compute_error", lambda *_: pytest.fail("Compute probe should not start"))
    assert main(["--config", str(config_file), "check-runtime", "--results-dir", str(tmp_path)]) == 2
    result = capsys.readouterr()
    assert "synthetic-private-filename" not in result.err + result.out
    failure = json.loads(result.err)
    assert failure["error_code"] == "RUNTIME_CHECK_FAILED"
    assert failure["errors"] == ["MEDIA_TOOL_UNAVAILABLE:ffmpeg", "MISSING:asr", "UNMANIFESTED:asr"]


def test_check_runtime_checks_disk_and_passes_selected_profile(tmp_path, monkeypatch, capsys):
    config = {**model_fixture(tmp_path), "device": "cpu", "compute_type": "float32"}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(runtime, "_check_media_tools", lambda _: [])
    calls = []

    def check_compute(device, compute_type, cancel):
        calls.append((device, compute_type, cancel))

    monkeypatch.setattr(runtime, "_compute_error", check_compute)
    args = ["--config", str(config_file), "check-runtime", "--results-dir", str(tmp_path / "new"), "--profile", "memory"]
    assert main(args) == 0
    assert calls == [("cpu", "int8", None)]
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
    assert not (tmp_path / "new").exists()

    def full_disk(_):
        raise MediaError("INSUFFICIENT_DISK_SPACE", "Synthetic test")

    monkeypatch.setattr(runtime, "check_space", full_disk)
    assert main(args) == 2
    assert json.loads(capsys.readouterr().err)["errors"] == ["INSUFFICIENT_DISK_SPACE"]
    assert len(calls) == 1


def test_unc_config_rejected_before_read(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("UNC configuration was read"))
    with pytest.raises(ConfigurationError, match="local drive"):
        load_config(Path(r"\\server\share\config.json"))
