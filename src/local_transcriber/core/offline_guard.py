"""Fail closed before importing ML libraries. OS blocking is checked separately."""
import os
import socket
from pathlib import Path
from contextlib import ExitStack, contextmanager
from unittest.mock import patch


class NetworkDisabledError(OSError):
    pass


TOKEN_VARIABLES = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN", "HF_TOKEN_PATH")


def offline_environment(cache_root: Path | None = None) -> dict:
    env = dict(os.environ)
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               HF_HUB_DISABLE_IMPLICIT_TOKEN="1", PYANNOTE_METRICS_ENABLED="0",
               OTEL_SDK_DISABLED="true", DO_NOT_TRACK="1", TOKENIZERS_PARALLELISM="false",
               HF_HUB_DISABLE_XET="1")
    for key in TOKEN_VARIABLES:
        env.pop(key, None)
    if cache_root is not None:
        cache_root = cache_root.resolve()
        env.update(HF_HOME=str(cache_root / "huggingface"), TORCH_HOME=str(cache_root / "torch"),
                   XDG_CACHE_HOME=str(cache_root), MPLCONFIGDIR=str(cache_root / "matplotlib"),
                   NUMBA_CACHE_DIR=str(cache_root / "numba"))
    return env


@contextmanager
def block_network():
    """Block Python DNS/TCP/UDP, including localhost. Not an OS firewall substitute."""
    def denied(*args, **kwargs):
        raise NetworkDisabledError("NETWORK_DISABLED")
    with ExitStack() as guards:
        for method in ("connect", "connect_ex", "sendto", "sendmsg", "sendfile"):
            if hasattr(socket.socket, method):
                guards.enter_context(patch.object(socket.socket, method, denied))
        for method in ("create_connection", "getaddrinfo", "getnameinfo",
                       "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
            guards.enter_context(patch.object(socket, method, denied))
        yield


@contextmanager
def offline_runtime(cache_root: Path | None = None):
    with patch.dict(os.environ, offline_environment(cache_root), clear=True), block_network():
        yield
