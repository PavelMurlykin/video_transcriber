from dataclasses import replace
import json
import subprocess
import sys
from threading import Thread
import time

import pytest

from local_transcriber.config import PATH_FIELDS, load_config
from local_transcriber.core import pipeline
from local_transcriber.domain.entities import TranscriptionJob
from local_transcriber.ui.settings import RunRequest, Settings


@pytest.fixture
def settings(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({key: str(tmp_path / key) for key in PATH_FIELDS}), encoding="utf-8")
    return Settings.load(config, tmp_path / "config.ui.local.json")


def test_desktop_settings_and_run_config_are_separate(settings, tmp_path):
    assert settings.active_config == settings.base_config
    new = replace(settings, results=tmp_path / "private", language="en", theme="dark")
    new.save()
    assert new.active_config == new.preferences
    assert Settings.load(new.base_config, new.preferences) == new

    request = RunRequest(tmp_path / "Тестовая запись.mp4", "ru", 3, "memory")
    args, snapshot, cancellation = request.prepare(new)
    assert args[4:6] == ["transcribe", str(request.source)]
    assert args[-4:] == ["--profile", "memory", "--cancel-file", str(cancellation)]
    assert load_config(snapshot)["num_speakers"] == 3
    assert load_config(new.active_config)["num_speakers"] == 2
    assert not cancellation.exists() and not cancellation.with_suffix("").exists()
    args, second, _ = replace(request, language="en").prepare(new)
    assert args[4] == "asr" and args[-2:] == ["--language", "en"] and second != snapshot


def test_cancelled_inference_terminates_real_child_and_marks_stage(tmp_path, monkeypatch):
    ready = tmp_path / "ready"
    cancel = tmp_path / "cancel"
    job = TranscriptionJob(tmp_path / "media.wav", tmp_path, cancel_file=cancel)
    popen = subprocess.Popen
    processes = []

    def launch(_command, **kwargs):
        process = popen([sys.executable, "-c",
                         "from pathlib import Path; import sys,time; Path(sys.argv[1]).touch(); time.sleep(30)",
                         str(ready)], **kwargs)
        processes.append(process)
        return process

    def request_cancel():
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.touch()

    monkeypatch.setattr(pipeline, "gpu_memory_mib", lambda: None)
    monkeypatch.setattr(pipeline.subprocess, "Popen", launch)
    thread = Thread(target=request_cancel)
    thread.start()
    try:
        with pytest.raises(KeyboardInterrupt), job.stage("asr"):
            pipeline._run_inference("asr", job, tmp_path / "config.json", pipeline.ASROptions())
    finally:
        thread.join(timeout=6)
    assert ready.exists() and processes[0].poll() is not None
    assert job.stages["asr"] == "cancelled"
