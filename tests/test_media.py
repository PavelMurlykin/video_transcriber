import json
from pathlib import Path
import shutil
import subprocess
from threading import Event
from types import SimpleNamespace
import wave

import pytest

from local_transcriber.cli import main
from local_transcriber.core.media import prepare_audio
from local_transcriber.domain.errors import MediaError


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
    assert result == {"duration_ms": 1000, "sample_rate": 16000, "channels": 1,
                      "container": "wav", "audio_codec": "pcm_s16le",
                      "audio_sample_rate": 8000, "audio_channels": 2}
    assert original.read_bytes() == before
    assert sorted(tmp_path.iterdir()) == sorted([original, target])


def test_corrupt_input_fails_without_modification(tmp_path, ffmpeg_config):
    original = tmp_path / "corrupt.mp4"
    original.write_bytes(b"synthetic-invalid-media")
    target = tmp_path / "prepared.wav"
    with pytest.raises(MediaError) as error:
        prepare_audio(original, target, ffmpeg_config)
    assert error.value.code == "INVALID_MEDIA"
    assert not target.exists()
    assert original.read_bytes() == b"synthetic-invalid-media"


def test_cli_inspects_media_without_creating_prepared_audio(tmp_path, ffmpeg_config, capsys):
    source = tmp_path / "Метаданные.wav"
    make_media(ffmpeg_config, source, "-f", "lavfi", "-i", "sine=d=1:r=22050")
    settings = tmp_path / "config.json"
    settings.write_text(json.dumps(ffmpeg_config), encoding="utf-8")
    before = source.read_bytes()
    assert main(["--config", str(settings), "inspect-media", str(source)]) == 0
    metadata = json.loads(capsys.readouterr().out)
    assert metadata["estimated_duration_ms"] == 1000
    assert metadata["audio_sample_rate"] == 22050
    assert source.read_bytes() == before
    assert set(tmp_path.iterdir()) == {source, settings}


def test_no_audio_stream_fails(tmp_path, ffmpeg_config):
    original = tmp_path / "silent_video.mp4"
    subprocess.run([ffmpeg_config["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "color=black:s=32x32:d=0.2",
                    "-an", str(original)], check=True, capture_output=True)
    with pytest.raises(MediaError) as error:
        prepare_audio(original, tmp_path / "prepared.wav", ffmpeg_config)
    assert error.value.code == "NO_AUDIO_STREAM"


def test_refuses_to_overwrite_source(tmp_path, ffmpeg_config):
    original = tmp_path / "file.wav"
    original.write_bytes(b"original")
    with pytest.raises(MediaError) as error:
        prepare_audio(original, original, ffmpeg_config)
    assert error.value.code == "ORIGINAL_MUST_NOT_BE_OVERWRITTEN"
    assert original.read_bytes() == b"original"


def make_media(config, target, *options):
    subprocess.run([config["ffmpeg"], "-nostdin", "-v", "error", *options, str(target)],
                   check=True, capture_output=True, timeout=90)


def test_extracts_hour_long_video(tmp_path, ffmpeg_config):
    original = tmp_path / "час видео.mkv"
    make_media(ffmpeg_config, original, "-f", "lavfi", "-i", "color=s=16x16:r=1:d=3600",
               "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono:d=3600", "-c:v", "mpeg4", "-c:a", "flac")
    target = tmp_path / "prepared.wav"
    meta = prepare_audio(original, target, ffmpeg_config)
    assert meta["audio_codec"] == "flac"
    with wave.open(str(target), "rb") as audio:
        assert audio.getnframes() == 3600 * 16_000
    assert sorted(tmp_path.iterdir()) == sorted([original, target])


def test_cli_extracts_ima_adpcm_with_media_only_config(tmp_path, ffmpeg_config, capsys):
    original = tmp_path / "нестандартный кодек.wav"
    make_media(ffmpeg_config, original, "-f", "lavfi", "-i", "sine=d=1:r=22050", "-c:a", "adpcm_ima_wav")
    config_path = tmp_path / "ffmpeg.json"
    config_path.write_text(json.dumps(ffmpeg_config), encoding="utf-8")
    output_dir = tmp_path / "результат аудио"
    args = ["--config", str(config_path), "prepare-media", str(original), "--run-dir", str(output_dir)]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["audio_codec"] == "adpcm_ima_wav"
    assert result["sample_rate"] == 16_000
    assert result["channels"] == 1
    assert 1000 <= result["duration_ms"] <= 1100
    with (output_dir / "audio.wav").open("rb") as audio:
        assert audio.read(4) == b"RIFF"
    assert main(args) == 2
    assert json.loads(capsys.readouterr().err)["error_code"] == "RUN_DIRECTORY_ALREADY_EXISTS"


def test_low_disk_is_rejected_before_extraction(tmp_path, ffmpeg_config, monkeypatch):
    original = tmp_path / "input.wav"
    make_media(ffmpeg_config, original, "-f", "lavfi", "-i", "sine=d=1")
    real_popen = subprocess.Popen
    commands = []

    def track(command, *args, **kwargs):
        commands.append(command[0])
        return real_popen(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", track)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(MediaError) as error:
        prepare_audio(original, tmp_path / "prepared.wav", ffmpeg_config)
    assert error.value.code == "INSUFFICIENT_DISK_SPACE"
    assert commands == [ffmpeg_config["ffprobe"]]
    assert list(tmp_path.iterdir()) == [original]


def test_cancel_stops_ffmpeg_and_removes_partial_wav(tmp_path, ffmpeg_config, monkeypatch):
    original = tmp_path / "input.wav"
    make_media(ffmpeg_config, original, "-f", "lavfi", "-i", "sine=d=1")
    cancel = Event()
    spawned = []
    real_popen = subprocess.Popen

    def cancel_after_start(command, *args, **kwargs):
        if command[0] == ffmpeg_config["ffmpeg"]:
            Path(command[-1]).write_bytes(b"partial WAV")
        process = real_popen(command, *args, **kwargs)
        if command[0] == ffmpeg_config["ffmpeg"]:
            spawned.append(process)
            cancel.set()
        return process

    monkeypatch.setattr(subprocess, "Popen", cancel_after_start)
    with pytest.raises(KeyboardInterrupt):
        prepare_audio(original, tmp_path / "prepared.wav", ffmpeg_config, cancel=cancel)
    assert len(spawned) == 1 and spawned[0].poll() is not None
    assert list(tmp_path.iterdir()) == [original]


def test_refuses_to_overwrite_existing_audio(tmp_path, ffmpeg_config):
    original = tmp_path / "input.wav"
    target = tmp_path / "prepared.wav"
    original.write_bytes(b"source")
    target.write_bytes(b"prior result")
    with pytest.raises(MediaError) as error:
        prepare_audio(original, target, ffmpeg_config)
    assert error.value.code == "AUDIO_OUTPUT_EXISTS"
    assert target.read_bytes() == b"prior result"
