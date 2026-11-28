import json
from pathlib import Path
import sys

import pytest

from local_transcriber.config import load_config
from local_transcriber.launch import cli_command, default_path, prepare_default_config, worker_command


def test_source_launch_uses_python_module_routes():
    assert cli_command("check-runtime") == [sys.executable, "-u", "-m", "local_transcriber", "check-runtime"]
    assert worker_command("runtime_probe", "cuda", "float16") == [
        sys.executable, "-m", "local_transcriber.workers.runtime_probe", "cuda", "float16",
    ]
    assert default_path("config.local.json") == Path("config.local.json")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")
def test_installed_defaults_and_worker_routes(tmp_path, monkeypatch):
    exe = tmp_path / "install" / "LocalTranscriber.exe"
    assets = exe.parent / "_internal"
    assets.mkdir(parents=True)
    example = Path(__file__).resolve().parents[1] / "config.example.json"
    (assets / example.name).write_bytes(example.read_bytes())
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(assets), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    filename = default_path("config.local.json")
    assert filename == tmp_path / "local" / "LocalTranscriber" / "config.local.json"
    prepare_default_config(filename)
    data = load_config(filename)
    assert Path(data["ffprobe"]) == assets / "tools" / "ffprobe.exe"
    assert Path(data["asr"]) == tmp_path / "profile" / ".lmstudio" / "models" / "local-transcriber" / "whisper-large-v3"
    assert cli_command("check-runtime") == [str(exe.with_name("LocalTranscriberCLI.exe")), "check-runtime"]
    monkeypatch.setattr(sys, "executable", str(exe.with_name("LocalTranscriberCLI.exe")))
    assert worker_command("runtime_probe", "cuda", "float16") == [
        sys.executable, "--internal-runtime_probe", "cuda", "float16",
    ]
    filename.write_text(json.dumps({"custom": True}), encoding="utf-8")
    prepare_default_config(filename)
    assert json.loads(filename.read_text(encoding="utf-8")) == {"custom": True}
