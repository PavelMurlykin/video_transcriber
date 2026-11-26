import json
import os
from unittest.mock import patch

from local_transcriber.workers import transcription_worker


def test_worker_errors_never_log_exception_values(tmp_path, monkeypatch, capsys):
    secret = "synthetic-private-speech-and-token"
    monkeypatch.setattr("sys.argv", ["worker", "asr", "--config", str(tmp_path / "config.json"), "--run-dir", str(tmp_path)])
    monkeypatch.setattr(transcription_worker, "load_asr_config", lambda _: {})
    def fail(*args):
        print(secret)
        raise RuntimeError(secret)
    monkeypatch.setattr(transcription_worker, "execute", fail)
    with patch.dict(os.environ, dict(os.environ), clear=True):
        assert transcription_worker.main() == 1
    status = (tmp_path / "asr-status.json").read_text()
    captured = capsys.readouterr()
    assert secret not in status + captured.out + captured.err
    assert json.loads(status)["error_type"] == "RuntimeError"


def test_unknown_manifest_source_is_rejected(tmp_path):
    from test_models import model_fixture
    from local_transcriber.core.model_manager import verify_models
    from pathlib import Path
    config = model_fixture(tmp_path)
    path = Path(config["manifest"])
    manifest = json.loads(path.read_text())
    manifest["models"]["asr"]["source"] = "unapproved-model"
    path.write_text(json.dumps(manifest))
    assert "WRONG_SOURCE:manifest/asr" in verify_models(config)
