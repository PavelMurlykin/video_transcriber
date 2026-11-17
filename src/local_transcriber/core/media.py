"""Minimal stage-0 conversion; full media validation belongs to stage 1."""
import json
import subprocess
import wave
from pathlib import Path


def prepare_audio(source: Path, target: Path, config: dict) -> dict:
    if not source.is_file():
        raise FileNotFoundError("INPUT_NOT_FOUND")
    if source.resolve() == target.resolve():
        raise ValueError("ORIGINAL_MUST_NOT_BE_OVERWRITTEN")
    probe = subprocess.run([config["ffprobe"], "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "a:0", "-show_entries",
                            "stream=codec_name,sample_rate,channels:format=duration", "-of", "json", str(source)],
                           capture_output=True, check=True, text=True, encoding="utf-8")
    metadata = json.loads(probe.stdout)
    if not metadata.get("streams"):
        raise ValueError("NO_AUDIO_STREAM")
    subprocess.run([config["ffmpeg"], "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source),
                    "-map", "0:a:0", "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(target)],
                   capture_output=True, check=True)
    with wave.open(str(target), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        if duration <= 0 or audio.getnchannels() != 1 or audio.getframerate() != 16000 or audio.getsampwidth() != 2:
            raise ValueError("INVALID_PREPARED_WAV")
    return {"duration_ms": round(duration * 1000), "sample_rate": 16000, "channels": 1}
