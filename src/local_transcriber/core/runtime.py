"""Check local inference dependencies without loading model weights."""

from pathlib import Path
import subprocess
from tempfile import TemporaryFile
import time

from local_transcriber.domain.errors import MediaError
from local_transcriber.domain.paths import NonLocalPath, resolve_local
from local_transcriber.launch import worker_command
from local_transcriber.workers.runtime_probe import COMPUTE_UNSUPPORTED, CT2_FAILED, CUDA_UNAVAILABLE, TORCH_FAILED

from .media import CancelSignal, check_space
from .model_manager import MODEL_SPECS, verify_models
from .offline_guard import offline_environment

COMPUTE_TIMEOUT_SECONDS = 45
COMPUTE_ERRORS = {
    TORCH_FAILED: "TORCH_RUNTIME_FAILED",
    CUDA_UNAVAILABLE: "CUDA_UNAVAILABLE",
    CT2_FAILED: "CTRANSLATE2_RUNTIME_FAILED",
    COMPUTE_UNSUPPORTED: "COMPUTE_TYPE_UNSUPPORTED",
}


def _check_media_tools(config: dict) -> list[str]:
    errors = []
    for tool in ("ffmpeg", "ffprobe"):
        try:
            path = Path(config[tool])
            if not path.is_absolute():
                raise NonLocalPath
            executable = resolve_local(path, strict=True)
            result = subprocess.run(
                [str(executable), "-version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=offline_environment(), timeout=10, check=True,
            )
            if not result.stdout.startswith(f"{tool} version ".encode("ascii")):
                errors.append(f"MEDIA_TOOL_UNAVAILABLE:{tool}")
        except (OSError, NonLocalPath, subprocess.SubprocessError):
            errors.append(f"MEDIA_TOOL_UNAVAILABLE:{tool}")
    return errors


def _check_disk(directory: Path) -> list[str]:
    try:
        parent = resolve_local(directory)
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        check_space(parent)
        with TemporaryFile(dir=parent):
            pass
    except NonLocalPath:
        return ["OUTPUT_NOT_LOCAL"]
    except MediaError as error:
        return [error.code]
    except OSError:
        return ["RUN_DIRECTORY_UNWRITABLE"]
    return []


def _check_models(config: dict, *, asr_only: bool) -> list[str]:
    try:
        errors = verify_models(config, asr_only=asr_only)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return ["INVALID:manifest"]
    # Report trusted identifiers only. A manifest can contain arbitrary file names.
    allowed = {*MODEL_SPECS, "manifest", "vad", "nltk_data", "punkt_tab"}
    safe_errors = []
    for error in errors:
        kind, _, name = error.partition(":")
        root = name.split("/", 1)[0]
        safe_errors.append(f"{kind}:{root}" if root in allowed else "INVALID:manifest")
    return list(dict.fromkeys(safe_errors))


def _compute_error(device: str, compute_type: str, cancel: CancelSignal | None) -> str | None:
    command = worker_command("runtime_probe", device, compute_type)
    deadline = time.monotonic() + COMPUTE_TIMEOUT_SECONDS
    try:
        with subprocess.Popen(command, env=offline_environment(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
            try:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise KeyboardInterrupt
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return "COMPUTE_CHECK_TIMEOUT"
                    try:
                        code = process.wait(timeout=min(0.2, remaining))
                    except subprocess.TimeoutExpired:
                        continue
                    return COMPUTE_ERRORS.get(code, "COMPUTE_CHECK_FAILED") if code else None
            finally:
                if process.poll() is None:
                    process.kill()
    except OSError:
        return "COMPUTE_CHECK_FAILED"


def check_runtime(config: dict, directory: Path, *, asr_only: bool, compute_type: str,
                  cancel: CancelSignal | None = None) -> list[str]:
    errors = [*_check_disk(directory), *_check_media_tools(config), *_check_models(config, asr_only=asr_only)]
    if cancel is not None and cancel.is_set():
        raise KeyboardInterrupt
    if not errors:
        error = _compute_error(config["device"], compute_type, cancel)
        if error:
            errors.append(error)
    return errors
