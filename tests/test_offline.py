import os
import socket
from unittest.mock import patch

import pytest

from local_transcriber.core.offline_guard import NetworkDisabledError, block_network, offline_environment


def test_runtime_clears_tokens_and_disables_telemetry():
    with patch.dict(os.environ, {"HF_TOKEN": "test-secret", "HUGGING_FACE_HUB_TOKEN": "test-secret"}):
        env = offline_environment()
    assert "HF_TOKEN" not in env and "HUGGING_FACE_HUB_TOKEN" not in env
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["PYANNOTE_METRICS_ENABLED"] == "0"


@pytest.mark.parametrize("operation", [
    lambda: socket.getaddrinfo("example.invalid", 443),
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


def test_worker_cache_paths_are_isolated_from_user_cache(tmp_path):
    with patch.dict(os.environ, {"HF_HOME": "shared-user-cache", "TORCH_HOME": "shared-torch-cache"}):
        env = offline_environment(tmp_path / "run-cache")
    assert env["HF_HOME"] == str((tmp_path / "run-cache/huggingface").resolve())
    assert env["TORCH_HOME"] == str((tmp_path / "run-cache/torch").resolve())
