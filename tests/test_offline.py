import os
import socket
from unittest.mock import patch

import pytest

from local_transcriber.core.offline_guard import NetworkDisabledError, block_network, offline_environment, offline_runtime


def test_runtime_clears_tokens_and_disables_telemetry():
    with patch.dict(os.environ, {"HF_TOKEN": "test-secret", "HUGGING_FACE_HUB_TOKEN": "test-secret"}):
        env = offline_environment()
    assert "HF_TOKEN" not in env and "HUGGING_FACE_HUB_TOKEN" not in env
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["PYANNOTE_METRICS_ENABLED"] == "0"


@pytest.mark.parametrize("operation", [
    lambda: socket.getaddrinfo("example.invalid", 443),
    lambda: socket.gethostbyname("example.invalid"),
    lambda: socket.gethostbyname_ex("example.invalid"),
    lambda: socket.gethostbyaddr("127.0.0.1"),
    lambda: socket.getnameinfo(("127.0.0.1", 443), 0),
    lambda: socket.create_connection(("127.0.0.1", 80)),
    lambda: socket.socket().connect(("127.0.0.1", 80)),
    lambda: socket.socket().connect_ex(("127.0.0.1", 80)),
    lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"test", ("127.0.0.1", 53)),
])
def test_network_fails_closed(operation):
    with block_network(), pytest.raises(NetworkDisabledError):
        operation()


def test_guard_restores_socket_api():
    original = socket.socket.connect
    with block_network():
        assert socket.socket.connect is not original
    assert socket.socket.connect is original


def test_runtime_scope_prevents_using_environment_tokens(monkeypatch):
    for name in ("HF_TOKEN", "HF_TOKEN_PATH"):
        monkeypatch.setenv(name, "synthetic-secret")
    with offline_runtime():
        assert "HF_TOKEN" not in os.environ and "HF_TOKEN_PATH" not in os.environ
        assert os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"
        assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert os.environ["HF_TOKEN"] == "synthetic-secret"


def test_worker_cache_paths_are_isolated_from_user_cache(tmp_path):
    with patch.dict(os.environ, {"HF_HOME": "shared-user-cache", "TORCH_HOME": "shared-torch-cache"}):
        env = offline_environment(tmp_path / "run-cache")
    assert env["HF_HOME"] == str((tmp_path / "run-cache/huggingface").resolve())
    assert env["TORCH_HOME"] == str((tmp_path / "run-cache/torch").resolve())
