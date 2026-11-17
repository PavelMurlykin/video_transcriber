import json
from pathlib import Path
import subprocess
import wave

import pytest

from local_transcriber.core.media import prepare_audio


@pytest.fixture
def ffmpeg_config():
    info = Path(".tools/ffmpeg-install.json")
    if not info.exists():
        pytest.skip("local FFmpeg not prepared")
    return json.loads(info.read_text(encoding="utf-8-sig"))


def test_cyrillic_spaced_path_and_original_unchanged(tmp_path, ffmpeg_config):
    original = tmp_path / "Проверка записи с пробелами.wav"
    with wave.open(str(original), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0" * 8000 * 2 * 2)
    before = original.read_bytes()
    target = tmp_path / "prepared.wav"
    result = prepare_audio(original, target, ffmpeg_config)
    assert result == {"duration_ms": 1000, "sample_rate": 16000, "channels": 1}
    assert original.read_bytes() == before


def test_corrupt_input_fails_without_modification(tmp_path, ffmpeg_config):
    original = tmp_path / "corrupt.mp4"
    original.write_bytes(b"synthetic-invalid-media")
    with pytest.raises(subprocess.CalledProcessError):
        prepare_audio(original, tmp_path / "prepared.wav", ffmpeg_config)
    assert original.read_bytes() == b"synthetic-invalid-media"


def test_no_audio_stream_fails(tmp_path, ffmpeg_config):
    original = tmp_path / "silent_video.mp4"
    subprocess.run([ffmpeg_config["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "color=black:s=32x32:d=0.2",
                    "-an", str(original)], check=True, capture_output=True)
    with pytest.raises(ValueError, match="NO_AUDIO_STREAM"):
        prepare_audio(original, tmp_path / "prepared.wav", ffmpeg_config)


def test_refuses_to_overwrite_source(tmp_path, ffmpeg_config):
    original = tmp_path / "file.wav"
    original.write_bytes(b"original")
    with pytest.raises(ValueError, match="ORIGINAL_MUST_NOT_BE_OVERWRITTEN"):
        prepare_audio(original, original, ffmpeg_config)
    assert original.read_bytes() == b"original"
