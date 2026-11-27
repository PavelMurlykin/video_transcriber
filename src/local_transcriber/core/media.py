"""Inspect local media and extract a validated PCM WAV in the job's directory."""
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
from tempfile import TemporaryDirectory
import time
from typing import Protocol
import wave

from local_transcriber.domain.errors import MediaError
from local_transcriber.domain.paths import NonLocalPath, resolve_local

SAMPLE_RATE = 16_000
BYTES_PER_FRAME = 2
DISK_RESERVE_BYTES = 16 * 1024 * 1024
MAX_WAV_BYTES = (1 << 32) - 1
POLL_SECONDS = 0.2
PROBE_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class MediaInfo:
    container: str
    audio_codec: str
    audio_sample_rate: int | None
    audio_channels: int | None
    estimated_duration_ms: int | None


def create_run_directory(directory: Path) -> Path:
    try:
        directory = resolve_local(directory)
        directory.mkdir(parents=True, exist_ok=False)
    except NonLocalPath:
        raise MediaError("OUTPUT_NOT_LOCAL", "Choose an output directory on a local drive.") from None
    except FileExistsError:
        raise MediaError("RUN_DIRECTORY_ALREADY_EXISTS", "Choose a run directory that does not exist.") from None
    except OSError:
        raise MediaError("RUN_DIRECTORY_UNWRITABLE", "Choose a writable parent directory.") from None
    return directory


def _local_source(source: Path) -> Path:
    try:
        local = resolve_local(source, strict=True)
        if not stat.S_ISREG(local.stat().st_mode):
            raise MediaError("INPUT_NOT_FILE", "Choose a regular audio or video file.")
        with local.open("rb"):
            pass
    except NonLocalPath:
        raise MediaError("INPUT_NOT_LOCAL", "Choose a file on a local drive.") from None
    except FileNotFoundError:
        raise MediaError("INPUT_NOT_FOUND", "Check the input file path.") from None
    except OSError:
        raise MediaError("INPUT_UNREADABLE", "Check read access to the input file.") from None
    return local


def check_space(directory: Path, required_bytes: int = 0) -> None:
    free_bytes = shutil.disk_usage(directory).free
    if free_bytes < required_bytes + DISK_RESERVE_BYTES:
        raise MediaError(
            "INSUFFICIENT_DISK_SPACE",
            f"Free at least {required_bytes + DISK_RESERVE_BYTES:,} bytes on the output drive or select another drive.",
        )


def _wav_too_large() -> MediaError:
    return MediaError("WAV_TOO_LARGE", "Split the recording into parts that fit the 4 GiB PCM WAV size limit.")


class CancelSignal(Protocol):
    def is_set(self) -> bool: ...


def _check_cancel(cancel: CancelSignal | None) -> None:
    if cancel is not None and cancel.is_set():
        raise KeyboardInterrupt


def _run_tool(
    command: list[str],
    cancel: CancelSignal | None,
    *,
    partial: Path | None = None,
) -> tuple[int, bytes | None]:
    _check_cancel(cancel)
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdout=subprocess.PIPE if partial is None else subprocess.DEVNULL,
        )
    except OSError:
        raise MediaError("MEDIA_TOOL_UNAVAILABLE", "Check the configured FFmpeg and ffprobe executables.") from None
    deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS
    try:
        while True:
            _check_cancel(cancel)
            try:
                stdout, _ = process.communicate(timeout=POLL_SECONDS)
                _check_cancel(cancel)
                return process.returncode, stdout
            except subprocess.TimeoutExpired:
                if partial is None:
                    if time.monotonic() >= deadline:
                        raise MediaError("MEDIA_PROBE_TIMEOUT", "ffprobe timed out while inspecting the input file.")
                else:
                    check_space(partial.parent)
                    if partial.exists() and partial.stat().st_size >= MAX_WAV_BYTES:
                        raise _wav_too_large()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _duration_ms(value: object) -> int | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(seconds) and seconds > 0:
        # Saturation keeps absurd container timestamps on the disk/RIFF rejection path.
        return math.ceil(min(seconds, MAX_WAV_BYTES) * 1000)
    return None


def _probe(source: Path, config: dict, cancel: CancelSignal | None) -> MediaInfo:
    code, stdout = _run_tool([
        config["ffprobe"], "-v", "error", "-protocol_whitelist", "file,pipe",
        "-select_streams", "a:0", "-show_entries",
        "stream=codec_name,sample_rate,channels,duration:format=format_name,duration",
        "-of", "json", str(source),
    ], cancel)
    invalid_input = MediaError("INVALID_MEDIA", "ffprobe could not read the container. Check the file and its format.")
    if code:
        raise invalid_input
    try:
        metadata = json.loads(stdout)
    except (ValueError, TypeError):
        raise invalid_input from None
    if not metadata.get("streams"):
        raise MediaError("NO_AUDIO_STREAM", "Choose a file with an audio track.")
    stream = metadata["streams"][0]
    container = metadata.get("format", {})
    codec = stream.get("codec_name")
    if not codec or codec == "unknown":
        raise MediaError("UNSUPPORTED_AUDIO_CODEC", "ffprobe did not recognize the codec of the first audio track.")
    return MediaInfo(
        container=container.get("format_name", "unknown"), audio_codec=codec,
        audio_sample_rate=_positive_int(stream.get("sample_rate")), audio_channels=_positive_int(stream.get("channels")),
        estimated_duration_ms=_duration_ms(stream.get("duration")) or _duration_ms(container.get("duration")),
    )


def probe_media(source: Path, config: dict) -> dict:
    return asdict(_probe(_local_source(source), config, None))


def _check_wav(path: Path) -> int:
    if path.stat().st_size >= MAX_WAV_BYTES:
        raise _wav_too_large()
    invalid_wav = MediaError("INVALID_PREPARED_WAV", "The extracted WAV is empty, incomplete or has the wrong format.", exit_code=1)
    try:
        with wave.open(str(path), "rb") as audio:
            count = audio.getnframes()
            if count == 0 or (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, SAMPLE_RATE, BYTES_PER_FRAME):
                raise invalid_wav
            audio.setpos(count - 1)
            if len(audio.readframes(1)) != BYTES_PER_FRAME:
                raise invalid_wav
    except (EOFError, wave.Error):
        raise invalid_wav from None
    return max(1, round(count * 1000 / SAMPLE_RATE))


def prepare_audio(source: Path, target: Path, config: dict, *, cancel: CancelSignal | None = None) -> dict:
    """Return actual WAV metadata. The destination must be new and its parent must exist."""
    source = _local_source(source)
    if source == target.resolve():
        raise MediaError("ORIGINAL_MUST_NOT_BE_OVERWRITTEN", "Choose an output path different from the source.")
    target_exists = MediaError("AUDIO_OUTPUT_EXISTS", "Choose an output path that does not exist.")
    if target.exists() or target.is_symlink():
        raise target_exists
    info = _probe(source, config, cancel)
    estimate = math.ceil((info.estimated_duration_ms or 0) * SAMPLE_RATE * BYTES_PER_FRAME / 1000) + 4096
    if estimate >= MAX_WAV_BYTES:
        raise _wav_too_large()
    try:
        check_space(target.parent, estimate)
        with TemporaryDirectory(prefix=".audio-", dir=target.parent) as temporary:
            partial = Path(temporary) / "audio.wav"
            code, _ = _run_tool([
                config["ffmpeg"], "-nostdin", "-v", "error", "-xerror", "-n",
                "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:a:0",
                "-vn", "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", str(partial),
            ], cancel, partial=partial)
            if code:
                check_space(target.parent)
                raise MediaError("AUDIO_DECODE_FAILED", "FFmpeg could not decode the audio. Check the codec and file integrity.", exit_code=1)
            duration_ms = _check_wav(partial)
            _check_cancel(cancel)
            # Atomically publish without clobbering a destination created by another process.
            if os.name == "nt":
                partial.rename(target)
            else:
                os.link(partial, target)
    except FileExistsError:
        raise target_exists from None
    except OSError:
        raise MediaError("AUDIO_WRITE_FAILED", "Check that the output directory is writable and has free space.", exit_code=1) from None
    return {"duration_ms": duration_ms, "sample_rate": SAMPLE_RATE, "channels": 1,
            "container": info.container, "audio_codec": info.audio_codec,
            "audio_sample_rate": info.audio_sample_rate, "audio_channels": info.audio_channels}
